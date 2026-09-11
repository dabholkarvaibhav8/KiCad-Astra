"""Deterministic reference-label arrangement with native DRC as final geometry gate."""

import math
from dataclasses import asdict, dataclass

from shapely.geometry import box
from shapely.ops import unary_union

from agent.tools import empty_plan
from kicad.geometry import decode, encode, xy
from kicad.validation import ValidationReport


@dataclass(frozen=True)
class LabelStyle:
    height_mm: float = 1.0
    stroke_mm: float = 0.15
    clearance_mm: float = 0.2
    mask_margin_mm: float = 0.15
    edge_margin_mm: float = 0.3
    grid_mm: float = 0.25
    max_offset_mm: float = 5.0

    def checked(self):
        for key, value in asdict(self).items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{key} must be positive and finite")
        if self.stroke_mm > self.height_mm / 4 or self.grid_mm < 0.025:
            raise ValueError("Use stroke <= height/4 and grid >= 0.025 mm")
        return self


def capture_silkscreen(board, footprints, drawings):
    from kipy.board_types import BoardLayer

    sides = {BoardLayer.BL_F_SilkS: "front", BoardLayer.BL_B_SilkS: "back"}
    rows = []
    errors = []
    field_ids = set()
    candidates = []
    for fp in footprints:
        for kind, field in [
            ("reference", fp.reference_field),
            ("value", fp.value_field),
            ("field", fp.datasheet_field),
            ("field", fp.description_field),
        ]:
            field_ids.add(field.text.id.value)
            if field.visible:
                candidates.append((field.text, kind, fp.reference_field.text.value, fp.locked))
    candidates.extend((d, "graphic", "", False) for d in drawings if d.id.value not in field_ids)
    seen = set()
    for item, kind, ref, locked in candidates:
        if item.layer not in sides or item.id.value in seen:
            continue
        if hasattr(item, "value") and not item.value.strip():
            continue
        seen.add(item.id.value)
        try:
            bb = board.get_item_bounding_box(item, include_text=True)
            if not bb or bb.size.x <= 0 or bb.size.y <= 0:
                raise ValueError("Missing native bounding box")
            x, y = xy(bb.pos)
            w, h = xy(bb.size)
            row = {
                "id": item.id.value,
                "kind": kind,
                "reference": ref,
                "side": sides[item.layer],
                "locked": locked or bool(getattr(item, "locked", False)),
                "geometry": encode(box(x, y, x + w, y + h)),
            }
            if hasattr(item, "attributes"):
                row.update(
                    text=item.value,
                    position_mm=xy(item.position),
                    height_mm=item.attributes.size.y / 1e6,
                    stroke_mm=item.attributes.stroke_width / 1e6,
                )
            rows.append(row)
        except Exception as exc:
            errors.append(f"Silkscreen {ref or item.id.value}: {type(exc).__name__}")
    return rows, errors


def label_box(ref, x, y, style):
    width = max(style.height_mm, len(ref) * style.height_mm * 1.05) + 2 * style.stroke_mm
    height = style.height_mm + 2 * style.stroke_mm
    return box(x - width / 2, y - height / 2, x + width / 2, y + height / 2)


def arrange_labels(snapshot, rules, style=None, *, cancel=None):
    from agent.workflow import PlanBundle

    style = (style or LabelStyle()).checked()
    rules.checked()
    state = snapshot.state
    report = ValidationReport()
    report.errors.extend(state.get("silkscreen_errors", []))
    if not state.get("outline") or state.get("geometry_errors"):
        report.errors.append("Resolve board geometry before arranging labels")
    if "silkscreen" not in state:
        report.errors.append("Capture a fresh board with silkscreen metadata")
    rows = state.get("silkscreen", [])
    fps = {f["reference"]: f for f in state["footprints"]}
    movable = [
        r
        for r in rows
        if r["kind"] == "reference"
        and not r["locked"]
        and not fps.get(r["reference"], {}).get("locked", True)
    ]
    excluded = {r["id"] for r in movable}
    obstacles = {}
    ops = []
    for side in ("front", "back"):
        geom = [
            decode(r["geometry"]).buffer(style.clearance_mm)
            for r in rows
            if r["side"] == side and r["id"] not in excluded
        ]
        geom.extend(
            decode(f["courtyards"][side]).buffer(style.clearance_mm)
            for f in fps.values()
            if side in f["courtyards"]
        )
        layer = "F.Cu" if side == "front" else "B.Cu"
        geom.extend(
            decode(c["geometry"]).buffer(style.clearance_mm + style.mask_margin_mm)
            for c in state["copper"]
            if c["layer"] == layer and c["kind"] in {"pad", "via"}
        )
        geom.extend(decode(h["geometry"]).buffer(style.clearance_mm) for h in state["holes"])
        obstacles[side] = unary_union(geom)
    if not report.errors:
        inside = decode(state["outline"]).buffer(-style.edge_margin_mm)
        for row in sorted(movable, key=lambda r: r["reference"]):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Label arrangement cancelled")
            ref = row["reference"]
            side = row["side"]
            fp = fps[ref]
            if side not in fp["courtyards"]:
                report.errors.append(f"{ref}: missing same-side courtyard")
                continue
            body = decode(fp["courtyards"][side])
            x0, y0, x1, y1 = body.bounds
            width = label_box(ref, 0, 0, style).bounds[2] * 2
            height = style.height_mm + 2 * style.stroke_mm
            candidates = []
            for extra in (0, 0.5, 1, 2, 3):
                gap = style.clearance_mm + style.grid_mm + extra
                candidates.extend(
                    [
                        ((x0 + x1) / 2, y0 - height / 2 - gap),
                        ((x0 + x1) / 2, y1 + height / 2 + gap),
                        (x0 - width / 2 - gap, (y0 + y1) / 2),
                        (x1 + width / 2 + gap, (y0 + y1) / 2),
                    ]
                )
            chosen = None
            for x, y in candidates:
                x = round(x / style.grid_mm) * style.grid_mm
                y = round(y / style.grid_mm) * style.grid_mm
                g = label_box(ref, x, y, style)
                if (
                    g.distance(body) <= style.max_offset_mm
                    and inside.covers(g)
                    and not obstacles[side].intersects(g)
                ):
                    chosen = {
                        "id": row["id"],
                        "reference": ref,
                        "side": side,
                        "x_mm": x,
                        "y_mm": y,
                        "height_mm": style.height_mm,
                        "stroke_mm": style.stroke_mm,
                        "geometry": encode(g),
                    }
                    obstacles[side] = unary_union([obstacles[side], g.buffer(style.clearance_mm)])
                    break
            if chosen:
                ops.append(chosen)
            else:
                report.errors.append(f"{ref}: no clear label position; adjust manually")
                obstacles[side] = unary_union(
                    [obstacles[side], decode(row["geometry"]).buffer(style.clearance_mm)]
                )
    report.metrics["labels_arranged"] = len(ops)
    report.warnings.append(
        "Glyph bounds and mask margins are estimates. Native DRC and visual inspection remain required. Locked and hidden references are preserved."
    )
    bundle = PlanBundle(
        snapshot, empty_plan("Consistent, readable reference labels"), [], rules, report, "labels"
    )
    bundle.label_ops = ops
    return bundle


def stage_labels(board, operations):
    if not operations:
        return 0
    from kipy.board_types import BoardLayer
    from kipy.geometry import Vector2
    from kipy.proto.common.types.enums_pb2 import HA_CENTER, VA_CENTER

    fps = {f.reference_field.text.value: f for f in board.get_footprints()}
    changed = []
    poses = {}
    if len({o["reference"] for o in operations}) != len(operations):
        raise ValueError("Duplicate reference label operation")
    for op in operations:
        fp = fps.get(op["reference"])
        if fp is None or fp.locked or fp.reference_field.text.locked:
            raise ValueError("Missing or locked reference")
        text = fp.reference_field.text
        expected_layer = BoardLayer.BL_F_SilkS if op["side"] == "front" else BoardLayer.BL_B_SilkS
        if (
            text.id.value != op["id"]
            or text.layer != expected_layer
            or not fp.reference_field.visible
        ):
            raise ValueError("Reference identity, layer or visibility changed")
        poses[fp.id.value] = (xy(fp.position), fp.orientation.degrees, fp.layer)
        text.position = Vector2.from_xy_mm(op["x_mm"], op["y_mm"])
        a = text.attributes
        a.size = Vector2.from_xy_mm(op["height_mm"], op["height_mm"])
        a.stroke_width = round(op["stroke_mm"] * 1e6)
        a.angle = 0
        a.font_name = ""
        a.bold = False
        a.italic = False
        a.horizontal_alignment = HA_CENTER
        a.vertical_alignment = VA_CENTER
        a.mirrored = op["side"] == "back"
        a.keep_upright = True
        changed.append(fp)
    updated = board.update_items(changed)
    if len(updated) != len(changed) or {f.id.value for f in updated} != set(poses):
        raise RuntimeError("KiCad did not update all label owners")
    expected = {o["reference"]: o for o in operations}
    for fp in updated:
        op = expected.get(fp.reference_field.text.value)
        if not op or poses[fp.id.value] != (xy(fp.position), fp.orientation.degrees, fp.layer):
            raise RuntimeError("Label edit changed component identity or pose")
        t = fp.reference_field.text
        a = t.attributes
        layer = BoardLayer.BL_F_SilkS if op["side"] == "front" else BoardLayer.BL_B_SilkS
        if (
            t.id.value != op["id"]
            or t.layer != layer
            or not fp.reference_field.visible
            or math.dist(xy(t.position), (op["x_mm"], op["y_mm"])) > 2e-6
            or abs(a.size.x / 1e6 - op["height_mm"]) > 2e-6
            or abs(a.size.y / 1e6 - op["height_mm"]) > 2e-6
            or abs(a.stroke_width / 1e6 - op["stroke_mm"]) > 2e-6
            or a.angle != 0
            or a.font_name
            or a.bold
            or a.italic
            or a.horizontal_alignment != HA_CENTER
            or a.vertical_alignment != VA_CENTER
            or a.mirrored != (op["side"] == "back")
            or not a.keep_upright
        ):
            raise RuntimeError("KiCad changed/clamped a requested label operation")
    return len(updated)
