"""Build the bundled native parser and collect dependency license notices."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    portable = ROOT / ".validation/toolchain/go/bin/go.exe"
    go = str(portable) if portable.exists() else shutil.which("go")
    if not go:
        raise SystemExit("Install Go 1.25+ or run python scripts/bootstrap_go.py first (developer build only).")
    env = {**os.environ, "GOCACHE": str(ROOT / ".validation/go-cache"), "GOMODCACHE": str(ROOT / ".validation/go-mod-cache"), "CGO_ENABLED": "0"}
    binary = ROOT / "bin" / ("replay-parser.exe" if os.name == "nt" else "replay-parser")
    binary.parent.mkdir(exist_ok=True)
    subprocess.run([go, "test", "./..."], cwd=ROOT / "parser_helper", env=env, check=True)
    subprocess.run([go, "build", "-trimpath", "-ldflags=-s -w", "-o", str(binary), "."], cwd=ROOT / "parser_helper", env=env, check=True)
    modules = subprocess.check_output([go, "list", "-m", "-json", "all"], cwd=ROOT / "parser_helper", env=env, text=True)
    decoder, position, notices = json.JSONDecoder(), 0, []
    while position < len(modules):
        while position < len(modules) and modules[position].isspace():
            position += 1
        if position == len(modules):
            break
        module, position = decoder.raw_decode(modules, position)
        directory = Path(module.get("Dir", "."))
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "NOTICE"):
            path = directory / name
            if path.is_file() and not module.get("Main"):
                notices.append(f"{module['Path']} {module.get('Version', '')} — {name}\n{path.read_text(encoding='utf-8')}\n")
    go_root = Path(subprocess.check_output([go, "env", "GOROOT"], env=env, text=True).strip())
    notices.append("Go runtime\n" + (go_root / "LICENSE").read_text())
    licenses = ROOT / "third_party"
    licenses.mkdir(exist_ok=True)
    (licenses / "parser-licenses.txt").write_text("\n".join(notices), encoding="utf-8")
    print(f"Built {binary} ({binary.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
