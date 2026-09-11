"""Native copper construction with stable UUIDs for preview/apply equivalence."""

from __future__ import annotations

from uuid import UUID, uuid5


def layer_id(name):
    from kipy.board_types import BoardLayer
    from kipy.util.board_layer import is_copper_layer

    try:
        value = BoardLayer.Value("BL_" + name.replace(".", "_", 1))
    except ValueError as exc:
        raise ValueError(f"Unknown copper layer {name}.") from exc
    if not is_copper_layer(value):
        raise ValueError(f"{name} is not a copper layer.")
    return value


def stage_routes(board, routes):
    from kipy.board_types import BoardLayer, Track, Via, ViaType
    from kipy.geometry import Vector2

    nets = {net.name: net for net in board.get_nets()}
    existing = {item.id.value for item in [*board.get_tracks(), *board.get_vias()]}
    items = []
    tracks = 0
    vias = 0
    for route in routes:
        net = nets.get(route["net"])
        if net is None:
            raise ValueError(f"Unknown net {route['net']}.")
        namespace = UUID(route["id"])
        for sidx, segment in enumerate(route["segments"]):
            for pidx, (start, end) in enumerate(
                zip(segment["points_mm"], segment["points_mm"][1:])
            ):
                item = Track()
                item.id.value = str(uuid5(namespace, f"segment:{sidx}:{pidx}"))
                item.net = net
                item.layer = layer_id(segment["layer"])
                item.start = Vector2.from_xy_mm(*start)
                item.end = Vector2.from_xy_mm(*end)
                item.width = round(segment["width_mm"] * 1e6)
                items.append(item)
                tracks += 1
        for i, spec in enumerate(route["vias"]):
            item = Via()
            item.id.value = str(uuid5(namespace, f"via:{i}"))
            item.net = net
            item.position = Vector2.from_xy_mm(*spec["position_mm"])
            item.diameter = round(spec["diameter_mm"] * 1e6)
            item.drill_diameter = round(spec["drill_mm"] * 1e6)
            items.append(item)
            vias += 1
    if any(item.id.value in existing for item in items):
        raise ValueError(
            "This route has already been applied. Capture the board and make a new plan."
        )
    if not items:
        return 0, 0
    created = board.create_items(items)
    if len(created) != len(items) or {i.id.value for i in created} != {i.id.value for i in items}:
        raise RuntimeError("KiCad did not create every requested copper item.")
    # Check endpoints, layers, sizes and nets; the server may reject or clamp properties.
    by_id = {i.id.value: i for i in items}
    for item in created:
        requested = by_id[item.id.value]
        if item.net.name != requested.net.name:
            raise RuntimeError("KiCad assigned a different net.")
        if isinstance(requested, Track):
            if (
                not isinstance(item, Track)
                or item.layer != requested.layer
                or item.width != requested.width
                or item.start != requested.start
                or item.end != requested.end
            ):
                raise RuntimeError("KiCad altered a proposed track.")
        elif (
            not isinstance(item, Via)
            or item.position != requested.position
            or item.diameter != requested.diameter
            or item.drill_diameter != requested.drill_diameter
            or item.type != ViaType.VT_THROUGH
            or item.padstack.drill.start_layer != BoardLayer.BL_F_Cu
            or item.padstack.drill.end_layer != BoardLayer.BL_B_Cu
        ):
            raise RuntimeError("KiCad altered a proposed via.")
    return tracks, vias


def apply_routes(board, routes):
    commit = board.begin_commit()
    try:
        result = stage_routes(board, routes)
        board.push_commit(commit, "KiCad Astra routing")
        return result
    except BaseException:
        board.drop_commit(commit)
        raise
