"""Boundary, repair, installation, and real subprocess regression tests."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.tools import PlanFormatError, empty_plan, extract_json
from agent.workflow import generate
from examples.demo_scene import DemoSession, connection, demo_proposal, make_scene
from kicad.config import LayoutRules
from kicad.drc import run_drc_file
from kicad.router import route_connection
from kicad.transactions import board_lock
from scripts.install_plugin import install
from support.doctor import diagnose
from tests.test_validation import move


class ScriptedClient:
    def __init__(self, *proposals):
        self.proposals = iter(proposals)
        self.requests = []
        self.usage = {"calls": 0}

    def create_plan(self, **kwargs):
        self.requests.append(kwargs)
        self.usage["calls"] += 1
        item = next(self.proposals)
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item)


class HardeningTests(unittest.TestCase):
    def test_exponent_overflow_is_rejected_everywhere(self):
        with self.assertRaises(PlanFormatError):
            extract_json('{"proximity":[{"max_mm":1e999}]}')

    def test_regions_reject_3d_nonfinite_boolean_or_missing_coordinates(self):
        for points in (
            [[0, 0, 1], [1, 0, 1], [0, 1, 1]],
            [[0, 0], [1, 0], [0, float("nan")]],
            [[0, 0], [True, 0], [0, 1]],
            [],
        ):
            with self.subTest(points=points), self.assertRaises(ValueError):
                LayoutRules(placement_regions={"U1": points}).checked()

    def test_invalid_proximity_has_a_controlled_error(self):
        for value in (None, 3, "rule", {"a": "", "b": "C1.1", "max_mm": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LayoutRules(proximity=[value]).checked()

    def test_constraint_file_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rules.json"
            path.write_text('{"clearance_mm":0.2,"clearance_mm":0.01}')
            with self.assertRaises(ValueError):
                LayoutRules.load(path)

    def test_precancelled_direct_route_does_no_work(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            route_connection(connection(), make_scene(), LayoutRules(), cancel=cancel)

    def test_repair_uses_measured_errors_and_succeeds(self):
        client = ScriptedClient(move("J1", 8, 4), move())
        bundle = generate(client, DemoSession().capture(), "Place U1", "placement", LayoutRules())
        self.assertTrue(bundle.report.ok, bundle.report.as_text())
        self.assertEqual(client.usage["calls"], 2)
        self.assertIn("local_validation", client.requests[1]["feedback"])

    def test_repeated_invalid_proposal_stops_without_consuming_budget(self):
        invalid = move("J1", 8, 4)
        client = ScriptedClient(invalid, invalid)
        bundle = generate(
            client, DemoSession().capture(), "Place", "placement", LayoutRules(max_revisions=5)
        )
        self.assertEqual(client.usage["calls"], 2)
        self.assertFalse(bundle.report.ok)

    def test_schema_failure_gets_bounded_repair(self):
        client = ScriptedClient(PlanFormatError("bad schema"), empty_plan("Review"))
        bundle = generate(client, DemoSession().capture(), "Review", "review", LayoutRules())
        self.assertTrue(bundle.report.ok)
        self.assertIn("schema_error", bundle.history[0])

    def test_bad_settings_never_reach_api(self):
        client = ScriptedClient()
        with self.assertRaises(ValueError):
            generate(
                client, DemoSession().capture(), "Review", "review", LayoutRules(max_revisions=-1)
            )
        self.assertEqual(client.usage["calls"], 0)

    def test_reversed_connection_is_not_a_dropped_requirement(self):
        original = demo_proposal()
        revised = copy.deepcopy(original)
        c = revised["connections"][0]
        c["from_pad_id"], c["to_pad_id"] = c["to_pad_id"], c["from_pad_id"]
        bundle = generate(
            ScriptedClient(revised),
            DemoSession().capture(),
            "Route",
            "routing",
            LayoutRules(grid_mm=1),
            previous=original,
        )
        self.assertTrue(bundle.report.ok, bundle.report.as_text())

    def test_no_key_is_exposed_in_diagnostics(self):
        secret = "test-secret-must-not-appear"
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": secret}),
            patch("support.doctor.importlib.import_module"),
        ):
            report = diagnose()
        self.assertNotIn(secret, json.dumps(report))
        self.assertEqual(
            next(c for c in report["checks"] if c["name"] == "model_access")["status"], "not_run"
        )

    def test_atomic_install_and_upgrade_preserve_previous_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "plugins/kicad-astra"
            install(target)
            (target / "local-marker.txt").write_text("previous installation")
            result = install(target, upgrade=True)
            self.assertEqual(
                (Path(result["backup"]) / "local-marker.txt").read_text(), "previous installation"
            )
            self.assertFalse((target / "local-marker.txt").exists())
            self.assertTrue((target / "main.py").exists())

    def test_installer_does_not_replace_foreign_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "user-work"
            target.mkdir()
            (target / "keep.txt").write_text("keep")
            with self.assertRaises(ValueError):
                install(target, upgrade=True)
            self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_install_dry_run_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "missing/kicad-astra"
            install(target, dry_run=True)
            self.assertFalse(target.parent.exists())

    def test_another_process_cannot_enter_board_commit_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            board = Path(folder) / "test.kicad_pcb"
            code = "from kicad.transactions import board_lock\nimport sys\nwith board_lock(sys.argv[1]): print('entered')"
            with board_lock(board):
                child = subprocess.run(
                    [sys.executable, "-c", code, str(board)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            self.assertNotEqual(child.returncode, 0)
            self.assertIn("Another KiCad Astra instance", child.stderr)


class ProcessBoundaryTests(unittest.TestCase):
    def run_child(self, script, *, old_report=None, timeout=5, cancel=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            board = root / "board.kicad_pcb"
            board.write_text("fixture")
            child_script = root / "cli_fixture.py"
            child_script.write_text(script)
            if old_report is not None:
                board.with_suffix(".drc.json").write_text(json.dumps(old_report))
            real_popen = subprocess.Popen
            processes = []

            def launch(command, **kwargs):
                process = real_popen([sys.executable, str(child_script), *command[1:]], **kwargs)
                processes.append(process)
                return process

            with patch("kicad.drc.subprocess.Popen", side_effect=launch):
                try:
                    return run_drc_file("test-cli", board, timeout=timeout, cancel=cancel)
                finally:
                    self.assertTrue(
                        all(p.poll() is not None for p in processes), "Leaked child process"
                    )

    def test_successful_real_process_report_is_parsed(self):
        script = "import sys,json\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index('--output')+1]).write_text(json.dumps({'violations':[],'unconnected_items':[]}))"
        self.assertTrue(self.run_child(script).clean)

    def test_stale_report_cannot_hide_a_missing_new_report(self):
        with self.assertRaisesRegex(RuntimeError, "readable"):
            self.run_child("pass", old_report={"violations": [], "unconnected_items": []})

    def test_timeout_reaps_real_process(self):
        with self.assertRaises(TimeoutError):
            self.run_child("import time\ntime.sleep(10)", timeout=0.15)

    def test_cancel_reaps_real_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        try:
            with self.assertRaises(InterruptedError):
                self.run_child("import time\ntime.sleep(10)", cancel=cancel)
        finally:
            timer.cancel()

    def test_nonzero_exit_never_passes(self):
        with self.assertRaisesRegex(RuntimeError, "exit code 2"):
            self.run_child("raise SystemExit(2)")

    def test_malformed_category_is_rejected(self):
        script = "import sys,json\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index('--output')+1]).write_text(json.dumps({'violations':[],'unconnected_items':[],'schematic_parity':None}))"
        with self.assertRaisesRegex(RuntimeError, "category"):
            self.run_child(script)
