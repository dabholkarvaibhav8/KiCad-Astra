"""Read-only diagnostics with explicit pass/fail/not_run states."""

import importlib
import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys

from support import MIN_KICAD_VERSION, VERSION


def diagnose(*, connect=False, check_gui=False, check_api=False):
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    add("python", "pass" if sys.version_info >= (3, 11) else "fail", platform.python_version())
    for package, module in [
        ("openai", "openai"),
        ("kicad-python", "kipy"),
        ("shapely", "shapely"),
        ("numpy", "numpy"),
        ("jsonschema", "jsonschema"),
    ]:
        try:
            importlib.import_module(module)
            add(package, "pass", importlib.metadata.version(package))
        except (ImportError, OSError) as exc:
            add(package, "fail", f"{type(exc).__name__}: install requirements.txt with this Python")
    try:
        import tkinter as tk

        add("tkinter", "pass", f"Tk {tk.TkVersion}")
        if check_gui:
            root = tk.Tk()
            root.withdraw()
            root.update()
            root.destroy()
            add("desktop", "pass", "Created a real Tk window")
        else:
            add("desktop", "not_run", "Use --check-gui on a desktop")
    except Exception as exc:
        add(
            "desktop" if check_gui else "tkinter",
            "fail",
            f"{type(exc).__name__}: Tk/display unavailable",
        )
    cli = os.environ.get("KICAD_ASTRA_KICAD_CLI") or shutil.which("kicad-cli")
    if connect:
        try:
            from kicad.board_reader import KiCadBoardSession

            session = KiCadBoardSession.connect()
            snapshot = session.capture()
            add("ipc", "pass", str(session.kicad.get_version()))
            add(
                "board_geometry",
                "fail" if snapshot.state["geometry_errors"] else "pass",
                {"counts": snapshot.state["counts"], "errors": snapshot.state["geometry_errors"]},
            )
            cli = str(
                session.kicad.get_kicad_binary_path(
                    "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
                )
            )
        except Exception as exc:
            add("ipc", "fail", f"{type(exc).__name__}: {exc}")
    else:
        add("ipc", "not_run", "Use --connect with an open KiCad PCB editor")
    if cli:
        try:
            proc = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=15)
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", proc.stdout)
            ok = (
                proc.returncode == 0
                and match
                and tuple(map(int, match.groups())) >= MIN_KICAD_VERSION
            )
            add(
                "kicad_cli", "pass" if ok else "fail", proc.stdout.strip() or "Version check failed"
            )
        except (OSError, subprocess.TimeoutExpired):
            add("kicad_cli", "fail", "Could not execute KiCad CLI")
    else:
        add("kicad_cli", "not_run", "Not on PATH; IPC supplies its location when connected")
    key_present = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    add(
        "api_key",
        "pass" if key_present else "not_run",
        "Environment key configured"
        if key_present
        else "Set OPENAI_API_KEY or enter a key in the UI",
    )
    if check_api and key_present:
        try:
            from openai import OpenAI

            from agent.astra_client import DEFAULT_MODEL

            with OpenAI(timeout=20, max_retries=0) as client:
                client.models.retrieve(DEFAULT_MODEL)
            add("model_access", "pass", "Model metadata accessible; generation not tested")
        except Exception as exc:
            add(
                "model_access",
                "fail",
                f"{type(exc).__name__}: check model access, key, quota and connectivity",
            )
    else:
        add(
            "model_access",
            "fail" if check_api else "not_run",
            "--check-api requires an environment key; sends no board data",
        )
    return {
        "application": "KiCad Astra",
        "version": VERSION,
        "platform": platform.platform(),
        "interpreter": sys.executable,
        "checks": checks,
        "ok": all(c["status"] != "fail" for c in checks),
        "note": "Only pass entries were tested. Native edit/DRC round-trip and live generation are separate checks.",
    }


def as_text(report):
    return "\n".join(
        [
            f"KiCad Astra {report['version']} diagnostics",
            f"Python: {report['interpreter']}",
            *[f"{c['status'].upper():8} {c['name']}: {c['detail']}" for c in report["checks"]],
            report["note"],
        ]
    )
