"""Failures at the native edit/DRC boundary must not leave partial board edits."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from agent.workflow import evaluate
from examples.demo_scene import DemoSession, demo_proposal
from kicad.config import LayoutRules
from kicad.drc import DrcResult, new_issues, run_drc_file
from kicad.transactions import apply_checked, preview_drc


def result(*items):
    return DrcResult(5 if items else 0, {"violations": list(items), "unconnected_items": []})


def issue(description="Clearance 0.1 mm is below 0.2 mm"):
    return {
        "type": "clearance",
        "severity": "error",
        "description": description,
        "items": [{"uuid": "first"}, {"uuid": "second"}],
    }


class MemoryBoard:
    def __init__(self, source):
        self.source = source
        self.saved = None
        self.dropped = 0
        self.pushed = 0

    def begin_commit(self):
        self.saved = self.source
        return "commit"

    def drop_commit(self, commit):
        self.source = self.saved
        self.dropped += 1

    def push_commit(self, commit, description):
        self.pushed += 1

    def get_as_string(self):
        return self.source


class MemorySession:
    def __init__(self, snapshot, folder):
        self.snapshot = snapshot
        self.lock = threading.RLock()
        self.board = MemoryBoard(snapshot.source)
        self.board_path = Path(folder) / "test.kicad_pcb"
        self.kicad = NS(get_kicad_binary_path=lambda _: "mock-kicad-cli")

    def assert_current(self, fingerprint):
        if fingerprint != self.snapshot.fingerprint or self.board.source != self.snapshot.source:
            raise RuntimeError("Stale board")

    def save_copy(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.board.source, encoding="utf-8")
        path.with_suffix(".kicad_pro").write_text("{}", encoding="utf-8")

    def save_backup(self):
        path = self.board_path.parent / "backup" / self.board_path.name
        self.save_copy(path)
        return path


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        snapshot = DemoSession().capture()
        self.bundle = evaluate(demo_proposal(), snapshot, LayoutRules(grid_mm=1), "routing")
        self.session = MemorySession(snapshot, self.folder.name)

    @staticmethod
    def stage(session, bundle):
        session.board.source = "deterministic native candidate"
        return {"placements": 0, "track_segments": 5, "vias": 0}

    def preflight(self):
        with (
            patch("kicad.transactions._stage", side_effect=self.stage),
            patch("kicad.transactions.run_drc_file", return_value=result()),
        ):
            return preview_drc(self.session, self.bundle)

    def test_preflight_restores_board_before_cli_and_does_not_push(self):
        def drc(*args, **kwargs):
            self.assertEqual(self.session.board.source, self.bundle.snapshot.source)
            return result()

        with (
            patch("kicad.transactions._stage", side_effect=self.stage),
            patch("kicad.transactions.run_drc_file", side_effect=drc),
        ):
            receipt = preview_drc(self.session, self.bundle)
        self.assertTrue(receipt.ok)
        self.assertEqual(self.session.board.pushed, 0)
        self.assertEqual(self.session.board.dropped, 1)

    def test_partial_native_failure_is_rolled_back(self):
        def fail(session, bundle):
            session.board.source = "partial edit"
            raise RuntimeError("server rejected the second item")

        with patch("kicad.transactions._stage", side_effect=fail):
            with self.assertRaises(RuntimeError):
                preview_drc(self.session, self.bundle)
        self.assertEqual(self.session.board.source, self.bundle.snapshot.source)
        self.assertEqual(self.session.board.dropped, 1)

    def test_new_native_drc_issue_blocks_apply(self):
        with (
            patch("kicad.transactions._stage", side_effect=self.stage),
            patch("kicad.transactions.run_drc_file", side_effect=[result(), result(issue())]),
        ):
            receipt = preview_drc(self.session, self.bundle)
        self.assertFalse(receipt.ok)
        with self.assertRaises(ValueError):
            apply_checked(self.session, self.bundle, receipt)
        self.assertEqual(self.session.board.pushed, 0)

    def test_stale_board_rejects_before_edit(self):
        receipt = self.preflight()
        self.session.board.source = "user edit"
        with self.assertRaisesRegex(RuntimeError, "Stale"):
            apply_checked(self.session, self.bundle, receipt)
        self.assertEqual(self.session.board.source, "user edit")

    def test_changed_constraints_invalidate_receipt(self):
        receipt = self.preflight()
        self.bundle.rules.clearance_mm = 0.35
        with self.assertRaisesRegex(ValueError, "changed"):
            apply_checked(self.session, self.bundle, receipt)

    def test_apply_must_match_native_candidate_and_rollback_mismatch(self):
        receipt = self.preflight()

        def changed(session, bundle):
            session.board.source = "server changed/clamped an edit"
            return {}

        with patch("kicad.transactions._stage", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "differ"):
                apply_checked(self.session, self.bundle, receipt)
        self.assertEqual(self.session.board.source, self.bundle.snapshot.source)
        self.assertEqual(self.session.board.pushed, 0)

    def test_apply_is_one_undo_step_with_backup_audit_and_no_replay(self):
        receipt = self.preflight()
        with patch("kicad.transactions._stage", side_effect=self.stage):
            applied = apply_checked(self.session, self.bundle, receipt)
        self.assertEqual(self.session.board.pushed, 1)
        self.assertEqual(Path(applied["backup"]).read_text(), self.bundle.snapshot.source)
        audit = json.loads(
            Path(applied["backup"]).with_suffix(".kicad-astra-audit.json").read_text()
        )
        self.assertEqual(audit["applied"]["track_segments"], 5)
        self.assertTrue(receipt.consumed)
        with self.assertRaises(ValueError):
            apply_checked(self.session, self.bundle, receipt)


class DrcTests(unittest.TestCase):
    def test_diff_counts_duplicate_violations_and_worsening_clearance(self):
        self.assertEqual(new_issues(result(issue()), result(issue())), [])
        self.assertEqual(len(new_issues(result(issue()), result(issue(), issue()))), 1)
        self.assertEqual(
            len(new_issues(result(issue()), result(issue("Clearance 0.05 mm is below 0.2 mm")))), 1
        )

    def test_incomplete_native_report_never_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            board = Path(folder) / "test.kicad_pcb"
            board.write_text("fixture")
            process = Mock(returncode=0)
            process.poll.return_value = 0

            def start(*args, **kwargs):
                board.with_suffix(".drc.json").write_text('{"violations":[]}')
                return process

            with patch("kicad.drc.subprocess.Popen", side_effect=start):
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    run_drc_file("mock-kicad-cli", board)

    def test_precancelled_drc_does_not_launch_cli(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch("kicad.drc.subprocess.Popen") as popen:
            with self.assertRaises(InterruptedError):
                run_drc_file("mock-kicad-cli", "test.kicad_pcb", cancel=cancelled)
        popen.assert_not_called()
