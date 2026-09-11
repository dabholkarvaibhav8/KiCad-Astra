"""Install a source release atomically, retaining an upgrade backup."""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
ENTRIES = (
    "agent",
    "kicad",
    "ui",
    "support",
    "scripts",
    "tests",
    "examples",
    "validation",
    "icons",
    "docs",
    "plugin.json",
    "requirements.txt",
    "requirements-dev.txt",
    "main.py",
    "README.md",
    "VALIDATION.md",
    "CONTRIBUTING.md",
    "ROADMAP.md",
    "GITHUB_LAUNCH.md",
    "PROJECT_STRUCTURE.md",
    "CHANGELOG.md",
    "LICENSE",
    "constraints.example.json",
    "labels.example.json",
    "manufacturing.example.json",
    "pyproject.toml",
)


def default_destination(version):
    base = os.environ.get("KICAD_DOCUMENTS_HOME")
    if not base:
        base = Path.home() / (
            "Documents/KiCad" if sys.platform in {"win32", "darwin"} else ".local/share/KiCad"
        )
    return Path(base).expanduser() / version / "plugins" / "kicad-astra"


def install(destination, *, upgrade=False, dry_run=False):
    target = Path(destination).expanduser().absolute()
    if (
        target.is_symlink()
        or target == SOURCE
        or SOURCE in target.parents
        or target in SOURCE.parents
    ):
        raise ValueError(
            "Choose a separate plugin folder, not the source, its parent, or a symlink."
        )
    if target.exists():
        if not upgrade:
            raise FileExistsError("Plugin exists; use --upgrade to preserve and replace it.")
        try:
            existing = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Destination is not a KiCad Astra installation.") from exc
        if existing.get("identifier") != "io.nextbuilder.kicadastra":
            raise ValueError("Refusing to replace another plugin or unrelated folder.")
    result = {"destination": str(target), "backup": None, "dry_run": dry_run}
    if dry_run:
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".kicad-astra-install-", dir=target.parent))
    backup = None
    try:
        for name in ENTRIES:
            src = SOURCE / name
            if src.is_dir():
                shutil.copytree(
                    src,
                    stage / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
                )
            elif src.is_file():
                shutil.copy2(src, stage / name)
            else:
                raise FileNotFoundError(f"Incomplete release: {name}")
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = target.parent.parent / "kicad-astra-plugin-backups" / stamp / target.name
            backup.parent.mkdir(parents=True, exist_ok=False)
            target.replace(backup)
            result["backup"] = str(backup)
        try:
            stage.replace(target)
        except BaseException:
            if backup and not target.exists():
                backup.replace(target)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-version", default="10.0")
    parser.add_argument("--destination", type=Path, help="Complete destination plugin folder")
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+", args.kicad_version):
        parser.error("Use major.minor, for example 10.0")
    try:
        print(
            json.dumps(
                install(
                    args.destination or default_destination(args.kicad_version),
                    upgrade=args.upgrade,
                    dry_run=args.dry_run,
                ),
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
