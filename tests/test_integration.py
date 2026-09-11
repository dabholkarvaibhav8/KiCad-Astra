"""Opt-in external checks; skipped checks are never recorded as passes."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.native_cli
def test_real_kicad_drc_accepts_compiled_route_and_detects_short(tmp_path):
    if os.environ.get("KICAD_ASTRA_TEST_NATIVE_CLI") != "1":
        pytest.skip("Set KICAD_ASTRA_TEST_NATIVE_CLI=1 and configure native test binaries")
    from examples.demo_scene import connection, make_scene
    from kicad.config import LayoutRules
    from kicad.drc import new_issues, run_drc_file
    from kicad.router import route_connection

    cli = os.environ.get("KICAD_ASTRA_KICAD_CLI") or shutil.which("kicad-cli")
    native_python = os.environ.get("KICAD_ASTRA_KICAD_PCBNEW_PYTHON")
    assert cli and native_python, "Set KICAD_ASTRA_KICAD_CLI and KICAD_ASTRA_KICAD_PCBNEW_PYTHON"
    routes = [route_connection(connection(), make_scene(), LayoutRules())]
    route_file = tmp_path / "routes.json"
    route_file.write_text(json.dumps(routes), encoding="utf-8")
    generator = Path(__file__).resolve().parents[1] / "scripts/generate_native_fixture.py"
    process = subprocess.run(
        [native_python, str(generator), "--output", str(tmp_path), "--routes", str(route_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    results = {
        name: run_drc_file(cli, tmp_path / (name + ".kicad_pcb"))
        for name in ("kicad-astra-native-fixture", "candidate", "shorted")
    }
    added = new_issues(results["kicad-astra-native-fixture"], results["candidate"])
    shorts = new_issues(results["candidate"], results["shorted"])
    evidence = os.environ.get("KICAD_ASTRA_TEST_EVIDENCE")
    if evidence:
        target = Path(evidence)
        target.mkdir(parents=True, exist_ok=True)
        for path in tmp_path.iterdir():
            if path.is_file():
                shutil.copy2(path, target / path.name)
        (target / "summary.json").write_text(
            json.dumps(
                {
                    "fixture_generator": process.stdout.strip(),
                    "counts": {name: result.violation_count for name, result in results.items()},
                    "candidate_new_issues": added,
                    "short_new_issues": shorts,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    assert not added, added
    assert len(results["candidate"].report["unconnected_items"]) < len(
        results["kicad-astra-native-fixture"].report["unconnected_items"]
    )
    assert shorts and any(
        item.get("type") in {"shorting_items", "clearance", "tracks_crossing"}
        and item.get("severity") == "error"
        for item in shorts
    ), shorts


@pytest.mark.gui
def test_real_desktop_demo_preview_export_and_controls(tmp_path):
    if os.environ.get("KICAD_ASTRA_TEST_GUI") != "1":
        pytest.skip("Set KICAD_ASTRA_TEST_GUI=1 with a real desktop display")
    import tkinter as tk

    from examples.demo_scene import DemoSession
    from ui.assistant_panel import AssistantPanel

    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
    try:
        with patch(
            "ui.assistant_panel.messagebox.showerror",
            side_effect=lambda *a, **k: errors.append(str(a)),
        ):
            panel = AssistantPanel(root, DemoSession())
            deadline = time.monotonic() + 15
            while (panel.busy or panel.bundle is None) and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert not panel.busy and panel.bundle is not None
            assert not errors, errors
            assert panel.bundle.report.ok
            assert len(panel.preview.canvas.find_all()) > 10
            assert panel.buttons["apply"].instate(["disabled"])
            assert panel.buttons["drc"].instate(["disabled"])
            panel.preview.select("U1")
            assert "U1" in panel.selection.cget("text")
            panel.preview.layer.set("F.Cu")
            panel.preview.draw()
            panel.preview.overlay.set(False)
            panel.preview.draw()
            target = tmp_path / "session.json"
            with patch("ui.assistant_panel.filedialog.asksaveasfilename", return_value=str(target)):
                panel._export()
            assert target.is_file()
            assert panel.buttons["manufacture"].instate(["disabled"])
            with patch("ui.assistant_panel.filedialog.askopenfilename", return_value=""):
                panel._labels()
            deadline = time.monotonic() + 10
            while panel.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert not errors, errors
            assert not panel.busy and panel.bundle.mode == "labels"
            assert len(panel.bundle.label_ops) == 2
            assert panel.bundle.report.ok
            panel.preview.overlay.set(True)
            panel.preview.draw()
            assert len(panel.preview.canvas.find_withtag("label-proposal")) == 2
            with patch("ui.assistant_panel.filedialog.asksaveasfilename", return_value=str(target)):
                panel._export()
            assert len(json.loads(target.read_text())["label_ops"]) == 2
            panel._cancel()
            assert panel.cancel.is_set()
    finally:
        root.destroy()


@pytest.mark.native
def test_native_fixture_preview_restores_editor():
    if os.environ.get("KICAD_ASTRA_TEST_NATIVE") != "1":
        pytest.skip("Set KICAD_ASTRA_TEST_NATIVE=1 with the generated fixture open in KiCad")
    from agent.tools import empty_plan
    from agent.workflow import evaluate
    from kicad.board_reader import KiCadBoardSession
    from kicad.config import LayoutRules
    from kicad.transactions import preview_drc

    session = KiCadBoardSession.connect()
    assert session.board_path.name == "kicad-astra-native-fixture.kicad_pcb", (
        "Open only the disposable generated fixture"
    )
    snapshot = session.capture()
    fp = next(f for f in snapshot.state["footprints"] if f["reference"] == "U1")
    proposal = empty_plan("Native transaction self-test")
    proposal["placements"] = [
        {
            "reference": "U1",
            "x_mm": fp["position_mm"][0] + 1,
            "y_mm": fp["position_mm"][1],
            "rotation_deg": fp["rotation_deg"],
            "side": fp["side"],
            "reason": "Disposable fixture round-trip",
        }
    ]
    bundle = evaluate(proposal, snapshot, LayoutRules(), "placement")
    assert bundle.report.ok, bundle.report.as_text()
    receipt = preview_drc(session, bundle)
    session.assert_current(snapshot.fingerprint)
    assert receipt.ok, receipt.to_dict()


@pytest.mark.live_api
def test_live_model_review_on_synthetic_data():
    if os.environ.get("KICAD_ASTRA_TEST_LIVE_API") != "1":
        pytest.skip("Set KICAD_ASTRA_TEST_LIVE_API=1 to opt into a potentially billed API request")
    assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY is required"
    from agent.astra_client import PlannerClient
    from examples.demo_scene import make_scene

    client = PlannerClient(reasoning_effort="low")
    try:
        proposal = client.create_plan(
            board_state=make_scene(),
            request="Briefly review this synthetic test fixture. Propose no changes.",
            mode="review",
        )
        assert not proposal["placements"] and not proposal["connections"]
        assert client.usage["calls"] == 1
    finally:
        client.close()


@pytest.mark.native_cli
def test_real_label_cleanup_fabrication_and_profile_gate(tmp_path):
    if os.environ.get("KICAD_ASTRA_TEST_NATIVE_CLI") != "1":
        pytest.skip("Set KICAD_ASTRA_TEST_NATIVE_CLI=1 and configure native test binaries")
    from dataclasses import replace
    from zipfile import ZipFile

    from examples.demo_scene import DemoSession, connection
    from kicad.config import LayoutRules
    from kicad.labels import arrange_labels
    from kicad.manufacturing import FabricationProfile, create_package, sha
    from kicad.router import route_connection

    cli = os.environ.get("KICAD_ASTRA_KICAD_CLI") or shutil.which("kicad-cli")
    native_python = os.environ.get("KICAD_ASTRA_KICAD_PCBNEW_PYTHON")
    assert cli and native_python
    session = DemoSession()
    session.state["copper"] = [p for p in session.state["copper"] if p["kind"] == "pad"]
    for fp in session.state["footprints"]:
        fp["locked"] = False
    for row in session.state["silkscreen"]:
        row["locked"] = False
    snap = session.capture()
    rules = LayoutRules()
    bundle = arrange_labels(snap, rules)
    assert bundle.report.ok and len(bundle.label_ops) == 3
    routes = [route_connection(connection(), snap.state, rules)]
    (tmp_path / "routes.json").write_text(json.dumps(routes))
    (tmp_path / "labels.json").write_text(json.dumps(bundle.label_ops))
    generator = Path(__file__).resolve().parents[1] / "scripts/generate_native_fixture.py"
    result = subprocess.run(
        [
            native_python,
            str(generator),
            "--output",
            str(tmp_path),
            "--routes",
            str(tmp_path / "routes.json"),
            "--labels",
            str(tmp_path / "labels.json"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    board = tmp_path / "candidate.kicad_pcb"
    project = json.loads(board.with_suffix(".kicad_pro").read_text())
    project["board"] = {
        "design_settings": {"rule_severities": {"track_width": "ignore", "text_height": "ignore"}}
    }
    board.with_suffix(".kicad_pro").write_text(json.dumps(project))
    original = (sha(board), sha(board.with_suffix(".kicad_pro")))
    profile = FabricationProfile(require_schematic_parity=False)
    good = create_package(cli, board, tmp_path / "accepted", profile)
    width = create_package(
        cli, board, tmp_path / "blocked-width", replace(profile, min_track_width_mm=0.4)
    )
    text = create_package(
        cli, board, tmp_path / "blocked-text", replace(profile, min_silk_height_mm=2.0)
    )
    evidence = os.environ.get("KICAD_ASTRA_TEST_EVIDENCE")
    if evidence:
        shutil.copytree(tmp_path, Path(evidence) / "finishing", dirs_exist_ok=True)
    assert good["fabrication_checks_passed"], good["errors"]
    assert good["native_drc"]["count"] == 0
    assert good["native_drc"]["report"]["ignored_checks"] == []
    assert {"track_width", "text_height"}.issubset(good["reenabled_native_checks"])
    assert (sha(board), sha(board.with_suffix(".kicad_pro"))) == original
    with ZipFile(tmp_path / "accepted/kicad-astra-fabrication.zip") as z:
        assert z.testzip() is None
        assert len([n for n in z.namelist() if n.endswith(".gbr")]) == 7
        assert "placement.csv" in z.namelist()
    assert not width["fabrication_checks_passed"] and not text["fabrication_checks_passed"]
    assert any(i["type"] == "track_width" for i in width["native_drc"]["report"]["violations"])
    assert any(i["type"] == "text_height" for i in text["native_drc"]["report"]["violations"])
    assert not (tmp_path / "blocked-width/kicad-astra-fabrication.zip").exists()
