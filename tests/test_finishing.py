"""Behavior tests for reference labels and isolated fabrication preparation."""

import copy
import json
import threading
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from kipy.board_types import BoardLayer, FootprintInstance
from kipy.geometry import Vector2
from shapely.geometry import box

from examples.demo_scene import DemoSession, uid
from kicad.config import LayoutRules
from kicad.drc import DrcResult
from kicad.geometry import decode, encode, xy
from kicad.labels import LabelStyle, arrange_labels, capture_silkscreen, stage_labels
from kicad.manufacturing import FabricationProfile, create_package, run_export, sha
from kicad.quality import inspect_quality
from tests.test_native_adapter import footprint


def test_labels_are_deterministic_clear_and_preserve_source_and_locks():
    snap = DemoSession().capture()
    original = copy.deepcopy(snap.state)
    a = arrange_labels(snap, LayoutRules())
    b = arrange_labels(snap, LayoutRules())
    assert a.report.ok, a.report.as_text()
    assert a.label_ops == b.label_ops
    assert {op["reference"] for op in a.label_ops} == {"U1", "R1"}
    assert snap.state == original and a.has_changes
    for op in a.label_ops:
        g = decode(op["geometry"])
        assert decode(snap.state["outline"]).buffer(-0.3).covers(g)
        assert all(
            g.distance(decode(f["courtyards"]["front"])) >= 0.2 for f in snap.state["footprints"]
        )
        assert all(
            g.distance(decode(p["geometry"])) >= 0.35
            for p in snap.state["copper"]
            if p["kind"] == "pad"
        )
    old_hash = a.content_hash()
    a.label_ops[0]["x_mm"] += 1
    assert old_hash != a.content_hash()


def test_labels_block_incomplete_geometry_and_cannot_silently_skip_crowding():
    snap = DemoSession().capture()
    snap.state["silkscreen_errors"] = ["Missing native text bounds"]
    assert not arrange_labels(snap, LayoutRules()).report.ok
    snap.state["silkscreen_errors"] = []
    snap.state["silkscreen"].append(
        {
            "id": uid("large logo"),
            "kind": "graphic",
            "reference": "",
            "locked": True,
            "side": "front",
            "geometry": encode(box(0, 0, 30, 20)),
        }
    )
    result = arrange_labels(snap, LayoutRules())
    assert not result.report.ok and not result.label_ops
    assert any("no clear label" in e for e in result.report.errors)


@pytest.mark.parametrize(
    "style",
    [
        LabelStyle(height_mm=True),
        LabelStyle(height_mm=float("nan")),
        LabelStyle(stroke_mm=0.5),
        LabelStyle(grid_mm=0.001),
    ],
)
def test_invalid_label_style_is_rejected(style):
    with pytest.raises(ValueError):
        style.checked()


def test_label_cancellation_stops_before_operations():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        arrange_labels(DemoSession().capture(), LayoutRules(), cancel=cancel)


@pytest.mark.parametrize("back", [False, True])
def test_native_label_roundtrip_preserves_component_pose_and_pad(back):
    fp = footprint()
    old_pose = (xy(fp.position), fp.orientation.degrees, fp.layer)
    old_pad = fp.definition.pads[0].proto.SerializeToString()
    fp.reference_field.visible = True
    fp.reference_field.text.id.value = uid("U1.ref")
    fp.reference_field.layer = BoardLayer.BL_B_SilkS if back else BoardLayer.BL_F_SilkS
    op = {
        "reference": "U1",
        "id": uid("U1.ref"),
        "side": "back" if back else "front",
        "x_mm": 8.0,
        "y_mm": 9.0,
        "height_mm": 1.0,
        "stroke_mm": 0.15,
    }
    returned = []

    def update(items):
        returned.extend(FootprintInstance(i.proto) for i in items)
        return returned

    assert stage_labels(NS(get_footprints=lambda: [fp], update_items=update), [op]) == 1
    actual = returned[0]
    assert (xy(actual.position), actual.orientation.degrees, actual.layer) == old_pose
    assert actual.definition.pads[0].proto.SerializeToString() == old_pad
    assert actual.reference_field.text.attributes.mirrored is back
    assert xy(actual.reference_field.text.position) == (8.0, 9.0)


def test_native_clamped_label_response_is_rejected():
    fp = footprint()
    fp.reference_field.visible = True
    fp.reference_field.layer = BoardLayer.BL_F_SilkS
    fp.reference_field.text.id.value = uid("U1.ref")
    op = {
        "reference": "U1",
        "id": uid("U1.ref"),
        "side": "front",
        "x_mm": 8.0,
        "y_mm": 9.0,
        "height_mm": 1.0,
        "stroke_mm": 0.15,
    }

    def update(items):
        f = FootprintInstance(items[0].proto)
        f.reference_field.text.attributes.size = Vector2.from_xy_mm(0.5, 0.5)
        return [f]

    with pytest.raises(RuntimeError, match="clamped"):
        stage_labels(NS(get_footprints=lambda: [fp], update_items=update), [op])


def test_capture_hidden_reference_is_preserved_and_bbox_failure_blocks_labels():
    fp = footprint()
    fp.reference_field.text.id.value = uid("U1.ref")
    fp.reference_field.layer = BoardLayer.BL_F_SilkS
    fp.reference_field.visible = False
    board = NS(get_item_bounding_box=lambda *a, **k: None)
    rows, errors = capture_silkscreen(board, [fp], [fp.reference_field.text])
    assert not rows and not errors
    fp.reference_field.visible = True
    rows, errors = capture_silkscreen(board, [fp], [])
    assert not rows and errors


def test_quality_reports_measured_area_and_readability():
    report = inspect_quality(DemoSession().state)
    assert report["board_area_mm2"] == 600
    assert report["projected_courtyard_union_mm2"] == 12
    assert report["estimated_net_span_mm"] > 0
    assert len(report["findings"]) == 3


@pytest.mark.parametrize(
    "value",
    [
        {"min_track_width_mm": True},
        {"min_clearance_mm": float("inf")},
        {"extra": 1},
        {"copper_layers": ["F.Cu", "In1.Cu", "B.Cu"]},
        {"require_schematic_parity": "false"},
    ],
)
def test_malformed_fabrication_profile_rejected(value):
    with pytest.raises(ValueError):
        FabricationProfile.from_dict(value)


def saved_board(tmp_path):
    board = tmp_path / "sample.kicad_pcb"
    board.write_text('(kicad_pcb (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (5 "F.SilkS" user)))')
    board.with_suffix(".kicad_pro").write_text(
        json.dumps({"board": {"design_settings": {"rules": {"min_clearance": 0.5}}}})
    )
    return board


def test_fabrication_requires_saved_project_schematic_and_exact_stack(tmp_path):
    board = saved_board(tmp_path)
    profile = FabricationProfile()
    with pytest.raises(ValueError, match="root schematic"):
        create_package("unused", board, tmp_path / "fab", profile)
    p = replace(
        profile, require_schematic_parity=False, copper_layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    )
    with pytest.raises(ValueError, match="stack"):
        create_package("unused", board, tmp_path / "fab", p)
    (tmp_path / "fab").mkdir()
    with pytest.raises(FileExistsError):
        create_package("unused", board, tmp_path / "fab", profile)


def test_remaining_warning_blocks_exports_and_preserves_stricter_source_rules(tmp_path):
    board = saved_board(tmp_path)
    original = {p: sha(p) for p in tmp_path.iterdir()}
    profile = FabricationProfile(require_schematic_parity=False)

    def drc(binary, copy, **kwargs):
        rules = json.loads(copy.with_suffix(".kicad_pro").read_text())["board"]["design_settings"][
            "rules"
        ]
        assert rules["min_clearance"] == 0.5 and rules["min_track_width"] == 0.25
        assert kwargs["save_refilled"] and not kwargs["schematic_parity"]
        return DrcResult(
            5,
            {
                "violations": [{"type": "silk_overlap", "severity": "warning", "items": []}],
                "unconnected_items": [],
                "ignored_checks": [],
            },
        )

    def export(binary, args, log, **kwargs):
        assert args[:3] == ["pcb", "export", "stats"]
        from pathlib import Path

        Path(args[args.index("--output") + 1]).write_text(
            json.dumps({"board": {"has_outline": True, "board_thickness": "1.6000 mm"}})
        )

    with (
        patch("kicad.manufacturing.run_drc_file", side_effect=drc),
        patch("kicad.manufacturing.run_export", side_effect=export),
    ):
        report = create_package("unused", board, tmp_path / "fab", profile)
    assert report["status"] == "blocked" and not report["fabrication_checks_passed"]
    assert not (tmp_path / "fab/kicad-astra-fabrication.zip").exists()
    assert all(sha(p) == h for p, h in original.items())


def test_pre_cancelled_export_never_starts_process(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with patch("kicad.manufacturing.subprocess.Popen") as start, pytest.raises(InterruptedError):
        run_export("unused", [], tmp_path / "log", cancel=cancel)
    start.assert_not_called()
