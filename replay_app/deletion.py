"""Explicitly confirmed, nonrecursive deletion of immutable catalog snapshots.

This module is never called by scanning, startup or ordinary selection. On
Windows deletion uses a validated open handle, protecting against final-path
replacement between validation and unlink. Tests use disposable files only.
"""
from dataclasses import dataclass, replace
import os
from pathlib import Path
import sqlite3
import stat


class UnsafeDeletion(ValueError):
    pass


@dataclass(frozen=True)
class DeleteTarget:
    path: str
    root: str
    library_id: int
    match_key: str
    size: int
    mtime: int
    identity: tuple | None


@dataclass(frozen=True)
class DeletePlan:
    files: tuple[DeleteTarget, ...]
    errors: tuple[str, ...] = ()

    def subset(self, paths):
        paths = set(paths)
        if not paths.issubset({entry.path for entry in self.files}):
            raise UnsafeDeletion("Confirmation includes a file outside its immutable plan")
        return replace(self, files=tuple(entry for entry in self.files if entry.path in paths))


def identity(info):
    # Windows Python reports ctime differently through path-stat and fstat;
    # device/inode plus exact size/mtime are stable across both APIs.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def check_location(root, path, missing_ok=False):
    root, path = Path(root), Path(path)
    if not root.is_absolute() or not path.is_absolute() or path.suffix.lower() != ".dem":
        raise UnsafeDeletion("Only absolute catalog .dem paths can be deleted")
    if ".." in path.parts or ".." in root.parts or not path.is_relative_to(root) or path == root:
        raise UnsafeDeletion("Replay is outside its assigned library")
    # Walk every component, including ancestors of the configured library.
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            # An unavailable library cannot be mistaken for an individually missing replay.
            if missing_ok and current != root and current.is_relative_to(root):
                return None
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise UnsafeDeletion(f"Symlink/junction/reparse traversal refused: {current}")
        if current == path:
            if not stat.S_ISREG(info.st_mode):
                raise UnsafeDeletion("Target is not a regular replay file")
        elif not stat.S_ISDIR(info.st_mode):
            raise UnsafeDeletion(f"Path component is not a directory: {current}")
    if path.resolve() != path or root.resolve() != root:
        raise UnsafeDeletion("Replay path resolves outside its original location")
    return info


def make_delete_plan(store, keys):
    wanted = set(keys)
    targets, errors = [], []
    for match in store.catalog():
        if match["key"] not in wanted:
            continue
        for copy in match["copies"]:
            try:
                info = check_location(copy["library_path"], copy["path"], missing_ok=True)
                if info and (info.st_size != copy["size"] or info.st_mtime_ns != copy["mtime"]):
                    raise UnsafeDeletion("File changed since the last scan; rescan before deleting")
                targets.append(DeleteTarget(copy["path"], copy["library_path"], copy["library_id"], match["key"], copy["size"], copy["mtime"], identity(info) if info else None))
            except (OSError, ValueError) as exc:
                errors.append(f"{copy['path']}: {exc}")
    return DeletePlan(tuple(targets), tuple(errors))


def revalidate(target):
    info = check_location(target.root, target.path, missing_ok=True)
    if info is None:
        return None
    if target.identity is None or identity(info) != target.identity:
        raise UnsafeDeletion("File changed or was replaced after confirmation; not deleted")
    return info


def unlink_verified(target):
    """Delete this exact validated file; no shell, recursion, or glob expansion."""
    if os.name != "nt":
        revalidate(target)
        Path(target.path).unlink()
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(target.path, 0x10000 | 0x80, 7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    try:
        # fstat binds identity to this handle, not a possibly replaced pathname.
        opened_identity = identity(os.fstat(descriptor))
        if opened_identity != target.identity:
            raise UnsafeDeletion("Opened replay identity changed; not deleted")
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise UnsafeDeletion("Cannot verify the opened replay's final path")
        final = buffer.value
        if final.startswith("\\\\?\\UNC\\"):
            final = "\\\\" + final[8:]
        elif final.startswith("\\\\?\\"):
            final = final[4:]
        if Path(final) != Path(target.path):
            raise UnsafeDeletion("Opened replay resolved to a different path")
        revalidate(target)
        pending_delete = ctypes.c_ubyte(True)  # FILE_DISPOSITION_INFO.DeleteFile is BOOLEAN.
        if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(pending_delete), ctypes.sizeof(pending_delete)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        os.close(descriptor)  # Owns/closes the original Windows handle.


def delete_files(store, plan, confirmed=False, remove=unlink_verified):
    report = {"cancelled": not confirmed, "deleted": [], "missing": [], "failed": []}
    if not confirmed:
        return report
    for target in plan.files:
        stage = "validation"
        try:
            with store.connect() as db:
                row = db.execute("SELECT f.*, l.path AS root FROM files f JOIN libraries l ON l.id=f.library_id WHERE f.path=? AND f.present=1", (target.path,)).fetchone()
            if not row or row["library_id"] != target.library_id or row["root"] != target.root or row["size"] != target.size or row["mtime"] != target.mtime:
                raise UnsafeDeletion("Catalog/library changed since confirmation; not deleted")
            info = revalidate(target)
            if info is None:
                report["missing"].append(target.path)
            else:
                stage = "deletion"
                try:
                    remove(target)
                    report["deleted"].append(target.path)
                except FileNotFoundError:
                    report["missing"].append(target.path)
            stage = "catalog update"
            with store.connect() as db:
                db.execute("UPDATE files SET present=0 WHERE path=? AND library_id=?", (target.path, target.library_id))
        except (OSError, ValueError, sqlite3.Error) as exc:
            report["failed"].append({"path": target.path, "stage": stage, "error": str(exc)})
    return report
