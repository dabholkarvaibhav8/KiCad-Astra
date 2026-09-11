#!/usr/bin/env python3
"""KiCad entry point for the KiCad Astra layout assistant."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def main() -> int:
    from support import VERSION

    parser = argparse.ArgumentParser(description="KiCad Astra layout workbench")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--demo",
        action="store_true",
        help="Open a synthetic PCB preview without KiCad or an API key",
    )
    actions.add_argument("--doctor", action="store_true", help="Read-only environment diagnostics")
    parser.add_argument("--version", action="version", version=f"KiCad Astra {VERSION}")
    parser.add_argument(
        "--connect", action="store_true", help="With --doctor: inspect the active PCB"
    )
    parser.add_argument(
        "--check-gui", action="store_true", help="With --doctor: create a real Tk window"
    )
    parser.add_argument(
        "--check-api",
        action="store_true",
        help="With --doctor: check model metadata without sending board data",
    )
    parser.add_argument("--json", action="store_true", help="With --doctor: JSON output")
    args = parser.parse_args()
    if args.doctor:
        from support.doctor import as_text, diagnose

        report = diagnose(connect=args.connect, check_gui=args.check_gui, check_api=args.check_api)
        print(json.dumps(report, indent=2) if args.json else as_text(report))
        return 0 if report["ok"] else 1
    if args.connect or args.check_gui or args.check_api or args.json:
        parser.error("Diagnostic options require --doctor")
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as exc:
        print(
            "KiCad Astra requires Tk support in the Python interpreter selected "
            "by KiCad. Install Tkinter or select a Python build that includes it.",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 2

    try:
        from kicad.board_reader import KiCadBoardSession
        from ui.assistant_panel import AssistantPanel

        if args.demo:
            from examples.demo_scene import DemoSession

            session = DemoSession()
        else:
            session = KiCadBoardSession.connect()
    except Exception as exc:  # KiCad surfaces stdout/stderr for plugin failures.
        print(f"KiCad Astra startup failed: {exc}", file=sys.stderr)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "KiCad Astra",
                f"Could not start:\n\n{exc}\n\nRun main.py --doctor for diagnostics.",
            )
            root.destroy()
        except tk.TclError:
            pass
        return 1

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(
            f"KiCad Astra needs a desktop display: {exc}\nHeadless demo: python -m examples.run_offline",
            file=sys.stderr,
        )
        return 2
    AssistantPanel(root, session)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
