"""Preview and apply the same native operations; each preview is rolled back immediately."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from kicad.board_reader import digest
from kicad.drc import new_issues, run_drc_file
from kicad.labels import stage_labels
from kicad.placement import stage_placements
from kicad.routing import stage_routes


@contextlib.contextmanager
def board_lock(path):
    """OS advisory lock prevents two KiCad Astra processes from interleaving commits."""
    name = Path(tempfile.gettempdir()) / ("kicad-astra-" + digest(str(path)) + ".lock")
    with name.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            if name.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another KiCad Astra instance is editing this board.") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another KiCad Astra instance is editing this board.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass
class DrcReceipt:
    source_fingerprint: str
    bundle_hash: str
    candidate_digest: str
    baseline: object
    candidate: object
    added: list
    consumed: bool = False

    @property
    def ok(self):
        return not self.added and not self.consumed

    def to_dict(self):
        return {
            "ready_to_apply": self.ok,
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "new_issues": self.added,
            "remaining_issues": self.candidate.violation_count,
        }


def _stage(session, bundle):
    placements = stage_placements(session.board, bundle.proposal["placements"])
    tracks, vias = stage_routes(session.board, bundle.routes)
    labels = stage_labels(session.board, bundle.label_ops)
    return {"placements": placements, "track_segments": tracks, "vias": vias, "labels": labels}


def preview_drc(session, bundle, *, cancel=None, progress=None):
    if not bundle.report.ok:
        raise ValueError("Resolve local validation errors before native DRC.")
    if not bundle.has_changes:
        raise ValueError("This plan has no board changes to test.")
    with tempfile.TemporaryDirectory(prefix="kicad-astra-check-") as folder:
        baseline = Path(folder) / "baseline" / session.board_path.name
        candidate = Path(folder) / "candidate" / session.board_path.name
        with session.lock, board_lock(session.board_path):
            session.assert_current(bundle.fingerprint)
            binary = session.kicad.get_kicad_binary_path(
                "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
            )
            session.save_copy(baseline)
            if progress:
                progress("Capturing native KiCad candidate; avoid editor changes briefly…")
            commit = session.board.begin_commit()
            try:
                _stage(session, bundle)
                candidate_text = session.board.get_as_string()
                if digest(candidate_text) == digest(bundle.snapshot.source):
                    raise RuntimeError(
                        "KiCad did not expose staged changes. This build cannot preflight this plan."
                    )
                session.save_copy(candidate)
            finally:
                # The long CLI check runs only AFTER restoring the live board.
                session.board.drop_commit(commit)
            session.assert_current(bundle.fingerprint)
            if candidate.read_text(encoding="utf-8").strip() != candidate_text.strip():
                raise RuntimeError(
                    "KiCad's saved copy differs from the staged document; preflight is unavailable."
                )
            if (
                not baseline.with_suffix(".kicad_pro").exists()
                or not candidate.with_suffix(".kicad_pro").exists()
            ):
                raise RuntimeError(
                    "Native preview did not export project settings; DRC would be incomplete."
                )
        if progress:
            progress("Running KiCad DRC on the baseline copy…")
        before = run_drc_file(binary, baseline, cancel=cancel)
        if progress:
            progress("Running KiCad DRC on the proposed copy…")
        after = run_drc_file(binary, candidate, cancel=cancel)
        added = new_issues(before, after)
        return DrcReceipt(
            bundle.fingerprint, bundle.content_hash(), digest(candidate_text), before, after, added
        )


def apply_checked(session, bundle, receipt):
    if not bundle.report.ok or not receipt or not receipt.ok:
        raise ValueError(
            "A successful native DRC comparison is required before applying this plan."
        )
    if (
        receipt.bundle_hash != bundle.content_hash()
        or receipt.source_fingerprint != bundle.fingerprint
    ):
        raise ValueError("The checked plan or its constraints changed. Run DRC again.")
    with session.lock, board_lock(session.board_path):
        session.assert_current(bundle.fingerprint)
        backup = session.save_backup()
        # SaveCopy can expose project save behavior; recheck immediately before editing.
        session.assert_current(bundle.fingerprint)
        commit = session.board.begin_commit()
        try:
            changes = _stage(session, bundle)
            if digest(session.board.get_as_string()) != receipt.candidate_digest:
                raise RuntimeError(
                    "Native operations differ from the DRC-tested candidate; changes were rolled back."
                )
            session.board.push_commit(commit, "KiCad Astra verified layout plan")
        except BaseException:
            session.board.drop_commit(commit)
            raise
        receipt.consumed = True
        result = {
            **changes,
            "backup": str(backup),
            "remaining_drc_items": receipt.candidate.violation_count,
        }
        try:
            backup.with_suffix(".kicad-astra-audit.json").write_text(
                json.dumps(
                    {"session": bundle.to_dict(), "drc": receipt.to_dict(), "applied": result},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            result["audit_warning"] = (
                f"Board changes were applied, but the audit report could not be saved: {exc}"
            )
        return result
