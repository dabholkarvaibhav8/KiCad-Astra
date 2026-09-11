"""Run release checks and write a machine-readable readiness report."""

import argparse
import json
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/verification")
    parser.add_argument("--gui", action="store_true", help="Require a real Tk desktop test")
    parser.add_argument(
        "--native-cli", action="store_true", help="Require real CLI DRC of generated copper"
    )
    parser.add_argument(
        "--native", action="store_true", help="Require IPC fixture preview/rollback"
    )
    parser.add_argument(
        "--live-api",
        action="store_true",
        help="Opt into a potentially billed synthetic API request",
    )
    parser.add_argument(
        "--require-all", action="store_true", help="Fail if any integration test was skipped"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ("junit.xml", "coverage.json", ".coverage"):
        (output / name).unlink(missing_ok=True)
    env = dict(os.environ)
    env["COVERAGE_FILE"] = str(output / ".coverage")
    env["KICAD_ASTRA_TEST_EVIDENCE"] = str(output / "native-cli")
    for flag, key in [
        (args.gui, "KICAD_ASTRA_TEST_GUI"),
        (args.native_cli, "KICAD_ASTRA_TEST_NATIVE_CLI"),
        (args.native, "KICAD_ASTRA_TEST_NATIVE"),
        (args.live_api, "KICAD_ASTRA_TEST_LIVE_API"),
    ]:
        if flag:
            env[key] = "1"
    checks = []
    commands = [
        (
            "compile",
            [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                "agent",
                "kicad",
                "ui",
                "support",
                "scripts",
                "examples",
                "tests",
                "main.py",
            ],
        ),
        ("lint", [sys.executable, "-m", "ruff", "check", "."]),
        ("format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        (
            "tests",
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "-m",
                "pytest",
                "-q",
                f"--junitxml={output / 'junit.xml'}",
            ],
        ),
    ]
    for name, command in commands:
        with (output / f"{name}.log").open("w", encoding="utf-8") as log:
            process = subprocess.run(
                command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        checks.append(
            {"name": name, "passed": process.returncode == 0, "exit_code": process.returncode}
        )
        print(f"{name}: {'PASS' if process.returncode == 0 else 'FAIL'}", flush=True)
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-o", str(output / "coverage.json")],
        cwd=ROOT,
        env=env,
        capture_output=True,
    )
    cases = []
    if (output / "junit.xml").is_file():
        for case in ET.parse(output / "junit.xml").iter("testcase"):
            status = (
                "skipped"
                if case.find("skipped") is not None
                else "failed"
                if case.find("failure") is not None or case.find("error") is not None
                else "passed"
            )
            cases.append({"name": case.attrib.get("name"), "status": status})
    counts = {
        key: sum(c["status"] == key for c in cases) for key in ("passed", "failed", "skipped")
    }
    complete = bool(cases) and counts["skipped"] == 0
    passed = all(c["passed"] for c in checks) and bool(cases) and counts["failed"] == 0
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "checks": checks,
        "tests": counts,
        "cases": cases,
        "available_checks_passed": passed,
        "all_integration_checks_executed": complete,
        "readiness_gate_passed": passed and complete,
        "note": "A skipped external check is not a pass; this report does not certify a PCB for manufacture.",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "tests": counts,
                "report": str(output / "report.json"),
                "readiness_gate_passed": report["readiness_gate_passed"],
            },
            indent=2,
        )
    )
    return 0 if passed and (not args.require_all or complete) else 1


if __name__ == "__main__":
    raise SystemExit(main())
