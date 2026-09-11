"""Strict native fabrication preflight and isolated output preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from agent.tools import extract_json
from kicad.drc import run_drc_file
from support import VERSION


@dataclass(frozen=True)
class FabricationProfile:
    name: str = "Generic profile — confirm limits with your fabricator"
    copper_layers: list[str] = field(default_factory=lambda: ["F.Cu", "B.Cu"])
    board_thickness_mm: float = 1.6
    min_clearance_mm: float = 0.2
    min_track_width_mm: float = 0.25
    min_drill_mm: float = 0.3
    min_annular_ring_mm: float = 0.15
    min_edge_clearance_mm: float = 0.3
    min_silk_height_mm: float = 1.0
    min_silk_stroke_mm: float = 0.15
    min_silk_clearance_mm: float = 0.2
    require_schematic_parity: bool = True

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown or malformed fabrication profile")
        p = cls(**value)
        if not isinstance(p.name, str) or not p.name.strip():
            raise ValueError("Profile name is required")
        for key, v in asdict(p).items():
            if key.endswith("_mm") and (
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or v <= 0
            ):
                raise ValueError(f"{key} must be positive and finite")
        for key, limit in {
            "min_clearance_mm": 25,
            "min_track_width_mm": 25,
            "min_drill_mm": 25,
            "min_annular_ring_mm": 25,
            "min_edge_clearance_mm": 25,
            "min_silk_height_mm": 100,
            "min_silk_stroke_mm": 25,
            "min_silk_clearance_mm": 100,
        }.items():
            if getattr(p, key) > limit:
                raise ValueError(f"{key} exceeds KiCad's supported setting range")
        ls = p.copper_layers
        if (
            not isinstance(ls, list)
            or not 2 <= len(ls) <= 32
            or len(ls) % 2
            or any(not isinstance(x, str) or not re.fullmatch(r"(?:F|B|In\d+)\.Cu", x) for x in ls)
            or len(ls) != len(set(ls))
            or ls[0] != "F.Cu"
            or ls[-1] != "B.Cu"
        ):
            raise ValueError("Provide an ordered copper stack from F.Cu to B.Cu")
        if type(p.require_schematic_parity) is not bool:
            raise ValueError("require_schematic_parity must be boolean")
        return p

    def minima(self):
        return {
            "min_clearance": self.min_clearance_mm,
            "min_track_width": self.min_track_width_mm,
            "min_through_hole_diameter": self.min_drill_mm,
            "min_via_annular_width": self.min_annular_ring_mm,
            "min_copper_edge_clearance": self.min_edge_clearance_mm,
            "min_text_height": self.min_silk_height_mm,
            "min_text_thickness": self.min_silk_stroke_mm,
            "min_silk_clearance": self.min_silk_clearance_mm,
        }


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copper_layers(text):
    table = re.search(r"\(layers\s+((?:\([^()]+\)\s*)+)\)", text)
    if not table:
        raise ValueError("Unsupported native copper layer table")
    layers = re.findall(r'\(\s*\d+\s+"((?:F|B|In\d+)\.Cu)"\s+(?:signal|mixed|power)\b', table[1])
    if len(layers) < 2 or len(layers) != len(set(layers)):
        raise ValueError("Unsupported copper layers")
    return layers


def run_export(binary, args, log_path, *, cancel=None, timeout=180):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Fabrication export cancelled")
    with Path(log_path).open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(binary), *map(str, args)],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Fabrication export cancelled")
                if time.monotonic() > deadline:
                    raise TimeoutError("Native export timed out")
                time.sleep(0.1)
        except BaseException:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise
    if proc.returncode:
        raise RuntimeError(
            f"Native export failed ({proc.returncode}): {Path(log_path).read_text(errors='replace')[-2000:]}"
        )


def create_package(binary, board_path, output, profile, *, cancel=None, progress=None):
    profile = FabricationProfile.from_dict(asdict(profile))
    source = Path(board_path).resolve()
    dest = Path(output).resolve()
    if source.suffix != ".kicad_pcb" or not source.is_file():
        raise ValueError("Choose a saved native PCB")
    if dest.exists():
        raise FileExistsError("Choose a new output folder; existing files are not replaced")
    project = source.with_suffix(".kicad_pro")
    if not project.is_file():
        raise ValueError("A matching saved .kicad_pro is required")
    layers = copper_layers(source.read_text(encoding="utf-8"))
    if layers != profile.copper_layers:
        raise ValueError("Fabrication profile stack differs from the board")
    if profile.require_schematic_parity and not source.with_suffix(".kicad_sch").is_file():
        raise ValueError("Schematic parity needs a matching saved root schematic")
    paths = [source, project]
    if source.with_suffix(".kicad_dru").is_file():
        paths.append(source.with_suffix(".kicad_dru"))
    if profile.require_schematic_parity:
        paths.extend(sorted(source.parent.rglob("*.kicad_sch")))
    if len(paths) > 500 or sum(p.stat().st_size for p in paths) > 100_000_000:
        raise ValueError("Project exceeds bounded snapshot size")
    if any(p.is_symlink() for p in paths):
        raise ValueError("Resolve linked source files into the project")
    original = {str(p): sha(p) for p in paths}
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".kicad-astra-fab-", dir=dest.parent))
    report = {
        "product": "KiCad Astra",
        "version": VERSION,
        "status": "blocked",
        "fabrication_checks_passed": False,
        "assembly_ready": False,
        "errors": [],
        "profile": asdict(profile),
        "notes": [
            "Inspect the Gerbers and complete electrical, stackup and fabricator review before ordering.",
            "Placement CSV and assembly drawings require a verified BOM, MPNs, DNP/variant and orientation review.",
        ],
    }
    try:
        inputs = stage / "source"
        inputs.mkdir()
        for path in paths:
            target = inputs / path.relative_to(source.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if sha(target) != original[str(path)]:
                raise RuntimeError("Source changed while copying")
        board = inputs / source.name
        settings = extract_json(board.with_suffix(".kicad_pro").read_text())
        minima = (
            settings.setdefault("board", {})
            .setdefault("design_settings", {})
            .setdefault("rules", {})
        )
        for key, value in profile.minima().items():
            previous = minima.get(key, 0)
            if (
                isinstance(previous, bool)
                or not isinstance(previous, (int, float))
                or not math.isfinite(previous)
            ):
                raise ValueError(f"Invalid saved minimum {key}")
            maximum = 100 if key in {"min_text_height", "min_silk_clearance"} else 25
            if previous > maximum:
                raise ValueError(f"Saved minimum {key} exceeds KiCad's setting range")
            minima[key] = max(previous, value)
        board.with_suffix(".kicad_pro").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        if progress:
            progress("Running strict DRC with fabrication minima on an isolated copy…")
        drc = run_drc_file(
            binary,
            board,
            cancel=cancel,
            schematic_parity=profile.require_schematic_parity,
            save_refilled=True,
        )
        ignored = drc.report.get("ignored_checks")
        if not isinstance(ignored, list) or any(
            not isinstance(i, dict) or not isinstance(i.get("key"), str) or not i["key"]
            for i in ignored
        ):
            raise RuntimeError("Native DRC did not report which checks were ignored")
        report["reenabled_native_checks"] = [i["key"] for i in ignored]
        if ignored:
            # --severity-all cannot resurrect checks configured as 'ignore'.
            # Enable them on the copy, then rerun before claiming a clean gate.
            severities = settings["board"]["design_settings"].setdefault("rule_severities", {})
            if not isinstance(severities, dict):
                raise ValueError("Malformed native rule severities")
            for item in ignored:
                severities[item["key"]] = "warning"
            board.with_suffix(".kicad_pro").write_text(
                json.dumps(settings, indent=2), encoding="utf-8"
            )
            drc = run_drc_file(
                binary,
                board,
                cancel=cancel,
                schematic_parity=profile.require_schematic_parity,
                save_refilled=True,
            )
            if drc.report.get("ignored_checks") != []:
                raise RuntimeError("Some native DRC checks remain disabled; export blocked")
        report["native_drc"] = drc.to_dict()
        if not drc.clean:
            report["errors"].append(
                f"{drc.violation_count} remaining native DRC items; fabrication export blocked"
            )
        stats_path = stage / "board-statistics.json"
        run_export(
            binary,
            ["pcb", "export", "stats", "--format", "json", "--output", stats_path, board],
            stage / "statistics.log",
            cancel=cancel,
        )
        stats = extract_json(stats_path.read_text())
        report["statistics"] = stats
        thickness = stats.get("board", {}).get("board_thickness", "")
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s+mm\s*", thickness)
        if not m or abs(float(m[1]) - profile.board_thickness_mm) > 0.01:
            report["errors"].append("Board thickness differs from profile or cannot be verified")
        if stats.get("board", {}).get("has_outline") is not True:
            report["errors"].append("Native statistics do not confirm a board outline")
        if not report["errors"]:
            if progress:
                progress("Exporting fabrication and assembly reference files…")
            plots = stage / "fabrication"
            plots.mkdir()
            selected = layers + ["F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts"]
            directory = str(plots) + os.sep
            jobs = [
                (
                    [
                        "pcb",
                        "export",
                        "gerbers",
                        "--layers",
                        ",".join(selected),
                        "--no-protel-ext",
                        "--check-zones",
                        "--output",
                        directory,
                        board,
                    ],
                    "gerbers.log",
                ),
                (
                    [
                        "pcb",
                        "export",
                        "drill",
                        "--format",
                        "excellon",
                        "--excellon-units",
                        "mm",
                        "--excellon-separate-th",
                        "--generate-report",
                        "--output",
                        directory,
                        board,
                    ],
                    "drill.log",
                ),
                (
                    [
                        "pcb",
                        "export",
                        "pos",
                        "--format",
                        "csv",
                        "--units",
                        "mm",
                        "--side",
                        "both",
                        "--exclude-dnp",
                        "--output",
                        plots / "placement.csv",
                        board,
                    ],
                    "placement.log",
                ),
                (
                    [
                        "pcb",
                        "export",
                        "svg",
                        "--mode-multi",
                        "--layers",
                        "F.Fab,B.Fab,Edge.Cuts",
                        "--output",
                        directory,
                        board,
                    ],
                    "assembly.log",
                ),
            ]
            for args, log in jobs:
                run_export(binary, args, stage / log, cancel=cancel)
            gerbers = list(plots.glob("*.gbr"))
            if len(gerbers) != len(selected) or any(
                "M02*" not in p.read_text(errors="replace") for p in gerbers
            ):
                raise RuntimeError("Incomplete Gerber layer output")
            holes = stats.get("drill_holes")
            if not isinstance(holes, list) or holes and not list(plots.glob("*.drl")):
                raise RuntimeError("Missing or unverifiable drill output")
            if not (plots / "placement.csv").is_file() or not list(plots.glob("*.svg")):
                raise RuntimeError("Incomplete assembly reference outputs")
            (plots / "README.txt").write_text(
                "KiCad Astra fabrication output for engineer review.\nAll exports use the absolute board origin and millimetres. Confirm bottom-side placement conventions with your assembler.\nAssembly requires a checked BOM. Inspect every layer in a Gerber viewer before ordering.\n"
            )
            (plots / "SHA256SUMS.json").write_text(
                json.dumps(
                    {p.name: sha(p) for p in sorted(plots.iterdir()) if p.is_file()}, indent=2
                )
            )
            with ZipFile(stage / "kicad-astra-fabrication.zip", "w", ZIP_DEFLATED) as archive:
                for path in sorted(plots.iterdir()):
                    archive.write(path, path.name)
            report.update(status="exported_for_review", fabrication_checks_passed=True)
        if any(not p.is_file() or sha(p) != original[str(p)] for p in paths):
            raise RuntimeError("Source changed during fabrication preparation")
        report["source_sha256"] = original
        report["refilled_board_sha256"] = sha(board)
        (stage / "manufacturing-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        if dest.exists():
            raise FileExistsError("Output folder appeared while exporting")
        stage.rename(dest)
        return {**report, "output": str(dest)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--cli", default=os.environ.get("KICAD_ASTRA_KICAD_CLI") or shutil.which("kicad-cli")
    )
    args = parser.parse_args()
    if not args.cli:
        parser.error("Set --cli or KICAD_ASTRA_KICAD_CLI")
    try:
        profile = FabricationProfile.from_dict(extract_json(args.profile.read_text()))
        report = create_package(args.cli, args.board, args.output, profile, progress=print)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "output": report["output"],
                    "errors": report["errors"],
                },
                indent=2,
            )
        )
        return 0 if report["fabrication_checks_passed"] else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"KiCad Astra fabrication preparation failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
