"""Native DRC on isolated board/project copies, with cancellation and regression diff."""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DrcResult:
    return_code: int
    report: dict
    console: str = ""

    @property
    def items(self):
        return [
            (group, item)
            for group in ("violations", "unconnected_items", "schematic_parity")
            for item in self.report.get(group, [])
        ]

    @property
    def clean(self):
        return self.return_code == 0 and not self.items

    @property
    def violation_count(self):
        return len(self.items)

    def as_text(self):
        return json.dumps(
            {
                "clean": self.clean,
                "reported_items": self.violation_count,
                "report": self.report,
                "console": self.console,
            },
            indent=2,
        )

    def to_dict(self):
        return {
            "clean": self.clean,
            "count": self.violation_count,
            "return_code": self.return_code,
            "report": self.report,
        }


def run_drc_file(
    binary, board_path, *, cancel=None, timeout=180, schematic_parity=False, save_refilled=False
):
    path = Path(board_path)
    output = path.with_suffix(".drc.json")
    command = [
        str(binary),
        "pcb",
        "drc",
        "--format",
        "json",
        "--units",
        "mm",
        "--severity-all",
        "--all-track-errors",
        "--exit-code-violations",
        "--refill-zones",
        "--output",
        str(output),
        str(path),
    ]
    if schematic_parity:
        command.insert(-1, "--schematic-parity")
    if save_refilled:
        command.insert(-1, "--save-board")
    if cancel is not None and cancel.is_set():
        raise InterruptedError("DRC cancelled.")
    output.unlink(missing_ok=True)
    log_path = path.with_suffix(".drc.log")
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("DRC cancelled.")
                if time.monotonic() > deadline:
                    raise TimeoutError("KiCad DRC exceeded its time budget.")
                time.sleep(0.1)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    console = log_path.read_text(encoding="utf-8", errors="replace")[-20000:]
    if process.returncode not in {0, 5}:
        raise RuntimeError(f"KiCad DRC failed with exit code {process.returncode}: {console}")
    try:
        report = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("KiCad produced no readable JSON DRC report.") from exc
    if (
        not isinstance(report, dict)
        or not isinstance(report.get("violations"), list)
        or not isinstance(report.get("unconnected_items"), list)
    ):
        raise RuntimeError("Unsupported/incomplete DRC report format; no pass was recorded.")
    if any(
        not isinstance(report.get(k, []), list)
        for k in ("violations", "unconnected_items", "schematic_parity")
    ):
        raise RuntimeError("Malformed DRC category; expected arrays of violations.")
    if any(
        not isinstance(i, dict)
        or not isinstance(i.get("items", []), list)
        or any(not isinstance(child, dict) for child in i.get("items", []))
        for k in ("violations", "unconnected_items", "schematic_parity")
        for i in report.get(k, [])
    ):
        raise RuntimeError("Malformed DRC violation entry.")
    result = DrcResult(process.returncode, report, console)
    if process.returncode == 5 and not result.items:
        raise RuntimeError("KiCad reported violations but the JSON report did not list them.")
    return result


def issue_key(group, item):
    identifiers = []
    for child in item.get("items", []):
        # Native KiCad UUIDs preserve identity through footprint movement.
        uid = child.get("uuid")
        identifiers.append(str(uid) if uid else json.dumps(child, sort_keys=True))
    return (
        group,
        item.get("type", ""),
        item.get("severity", "error"),
        item.get("description", ""),
        tuple(sorted(identifiers)),
    )


def new_issues(baseline, candidate):
    available = Counter(issue_key(group, item) for group, item in baseline.items)
    added = []
    for group, item in candidate.items:
        key = issue_key(group, item)
        if available[key]:
            available[key] -= 1
        else:
            added.append({"category": group, **item})
    return added
