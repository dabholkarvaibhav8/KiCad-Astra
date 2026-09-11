"""Build a source archive with deterministic entries and SHA-256 manifest."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    hashes = {}
    files = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if (
            not path.is_file()
            or path.is_symlink()
            or any(
                (part.startswith(".") and part not in {".github", ".gitignore", ".gitattributes"})
                or part in {"__pycache__", "dist", "build"}
                for part in rel.parts
            )
        ):
            continue
        if (
            path.suffix in {".pyc", ".zip"}
            or path.name.startswith("core")
            or path.name == "SHA256SUMS.json"
        ):
            continue
        files.append((rel.as_posix(), path.read_bytes()))
    for name, data in files:
        hashes[name] = hashlib.sha256(data).hexdigest()
    files.append(("SHA256SUMS.json", (json.dumps(hashes, indent=2) + "\n").encode()))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in files:
            info = ZipInfo("kicad-astra/" + name, date_time=(2026, 9, 6, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive integrity check failed")
    return {
        "archive": str(output),
        "files": len(files),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist/kicad-astra-v1.0.0.zip"
    )
    print(json.dumps(build(parser.parse_args().output), indent=2))
