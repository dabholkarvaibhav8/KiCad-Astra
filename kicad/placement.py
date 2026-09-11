"""Native footprint edits without dropping non-geometric children."""

from __future__ import annotations

import math


def stage_placements(board, placements):
    from kipy.board_types import (
        BoardShape,
        BoardText,
        Field,
        Footprint3DModel,
        Pad,
        to_concrete_board_shape,
    )
    from kipy.geometry import Angle, Vector2

    by_ref = {fp.reference_field.text.value: fp for fp in board.get_footprints()}
    changed = []
    for op in placements:
        fp = by_ref.get(op["reference"])
        if fp is None or fp.locked:
            raise ValueError(f"{op['reference']} is missing or locked.")
        from kipy.board_types import BoardLayer

        side = "front" if fp.layer == BoardLayer.BL_F_Cu else "back"
        if side != op["side"]:
            raise ValueError("Side changes require manual KiCad placement.")
        for item in fp.definition.items:
            if not isinstance(item, (Pad, Field, BoardText, BoardShape, Footprint3DModel)):
                raise ValueError(f"Unsupported movable child: {type(item).__name__}")
            if isinstance(item, BoardShape) and type(to_concrete_board_shape(item)) is BoardShape:
                raise ValueError("Unsupported footprint graphic geometry.")
        # kipy 0.8's orientation setter rebuilds children and omits 3D model items.
        models = [i for i in fp.definition.items if isinstance(i, Footprint3DModel)]
        fp.position = Vector2.from_xy_mm(op["x_mm"], op["y_mm"])
        fp.orientation = Angle.from_degrees(op["rotation_deg"])
        fp.definition.items = [*fp.definition.items, *models]
        changed.append(fp)
    if not changed:
        return 0
    updated = board.update_items(changed)
    if len(updated) != len(changed) or {f.id.value for f in updated} != {
        f.id.value for f in changed
    }:
        raise RuntimeError("KiCad did not update every requested footprint.")
    requested = {op["reference"]: op for op in placements}
    for fp in updated:
        op = requested[fp.reference_field.text.value]
        expected_layer = BoardLayer.BL_F_Cu if op["side"] == "front" else BoardLayer.BL_B_Cu
        if fp.layer != expected_layer:
            raise RuntimeError("KiCad changed the footprint side.")
        if math.dist((fp.position.x / 1e6, fp.position.y / 1e6), (op["x_mm"], op["y_mm"])) > 2e-6:
            raise RuntimeError("KiCad changed/clamped the proposed footprint position.")
        if abs((fp.orientation.degrees - op["rotation_deg"] + 180) % 360 - 180) > 1e-4:
            raise RuntimeError("KiCad changed/clamped the proposed footprint orientation.")
    return len(updated)


def apply_placements(board, placements):
    commit = board.begin_commit()
    try:
        count = stage_placements(board, placements)
        board.push_commit(commit, "KiCad Astra placements")
        return count
    except BaseException:
        board.drop_commit(commit)
        raise
