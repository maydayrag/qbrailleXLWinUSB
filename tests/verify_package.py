"""Verify the final installation ZIP, manifest and all shipped source files."""
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify(path):
    path = Path(path)
    assert path.read_bytes()[:4] == b"PK\x03\x04", "Not a ZIP archive"
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None, "ZIP CRC failure"
        manifest = archive.read("manifest.ini")
        assert manifest == (ROOT / "manifest.ini").read_bytes()
        assert re.search(rb'^version\s*=\s*"1.5"\s*$', manifest, re.M)
        source = ROOT / "addon/brailleDisplayDrivers/qbrailleXLWinUSB.py"
        assert archive.read("brailleDisplayDrivers/qbrailleXLWinUSB.py") == source.read_bytes()
        compile(archive.read("brailleDisplayDrivers/qbrailleXLWinUSB.py"), source.name, "exec")
        for directory in ("doc", "locale"):
            for file in (ROOT / directory).rglob("*"):
                if file.is_file():
                    assert archive.read(file.relative_to(ROOT).as_posix()) == file.read_bytes()
        assert not any("__pycache__" in n or n.startswith("addon/") for n in archive.namelist())
    print(f"Verified ZIP, version 1.5, driver source and documentation: {path}")


if __name__ == "__main__":
    verify(sys.argv[1])
