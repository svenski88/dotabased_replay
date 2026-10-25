from pathlib import Path
import tempfile
import unittest

from scripts.package_release import payload_files, version_name


class ReleaseTests(unittest.TestCase):
    def test_release_versions_cannot_be_paths_or_shell_arguments(self):
        for value in ("v1.0", "1.1.2", "v2.0.0-beta.1"):
            self.assertEqual(version_name(value), value.removeprefix("v"))
        for value in ("", "v1", "../1.0", "1.0/extra", "1.0;echo", "--draft", "1.0\n"):
            with self.assertRaises(ValueError):
                version_name(value)

    def test_reject_extra_executable_and_private_database(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            (bundle / "DotaBasedReplay.exe").touch()
            internal = bundle / "_internal"
            internal.mkdir()
            duplicate = bundle / "DotaBasedReplayBlue.exe"
            duplicate.touch()
            with self.assertRaisesRegex(ValueError, "canonical executable"):
                payload_files(bundle)
            duplicate.unlink()
            (internal / "library.sqlite3-wal").touch()
            with self.assertRaisesRegex(ValueError, "user data"):
                payload_files(bundle)


if __name__ == "__main__":
    unittest.main()
