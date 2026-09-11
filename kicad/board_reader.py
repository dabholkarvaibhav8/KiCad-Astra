"""PCB snapshot with KiCad-supplied pad polygons and conservative obstacles."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from kicad.geometry import (
    CURVE_ERROR_MM,
    arc_points,
    closed_region,
    encode,
    from_kicad_polygon,
    shape_lines,
    xy,
)


def digest(value: Any) -> str:
    payload = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class BoardSnapshot:
    state: dict
    source: str
    fingerprint: str
    board_path: Path

    def model_packet(self, max_bytes=1_500_000) -> dict:
        # Local checking retains the entire scene. Never silently trim geometry.
        packet = {**self.state, "fingerprint": self.fingerprint}
        size = len(json.dumps(packet, separators=(",", ":")).encode())
        if size > max_bytes:
            raise ValueError(
                f"Snapshot is {size:,} bytes; limit is {max_bytes:,}. Use a smaller board for AI planning. Local preview/DRC remain available."
            )
        return packet


class KiCadBoardSession:
    def __init__(self, kicad, board):
        self.kicad, self.board = kicad, board
        self.lock = threading.RLock()
        self.initial_document = board.document.SerializeToString(deterministic=True)

    @classmethod
    def connect(cls):
        from kipy import KiCad

        kicad = KiCad(client_name="io.nextbuilder.kicadastra", timeout_ms=15000)
        kicad.ping()
        version = kicad.get_version()
        if (version.major, version.minor, version.patch) < (10, 0, 6):
            raise RuntimeError("KiCad Astra requires KiCad 10.0.6 or newer.")
        return cls(kicad, kicad.get_board())

    @property
    def board_path(self):
        path = Path(self.board.name)
        if not path.is_absolute():
            project_path = Path(self.board.document.project.path)
            if not project_path.is_absolute():
                raise RuntimeError("Save the board in a KiCad project before starting KiCad Astra.")
            path = project_path / path
        return path.resolve()

    def refresh(self):
        board = self.kicad.get_board()
        if board.document.SerializeToString(deterministic=True) != self.initial_document:
            raise RuntimeError(
                "The active KiCad document changed. Reopen KiCad Astra for that board."
            )
        self.board = board

    def identity(self, text=None):
        self.refresh()
        text = self.board.get_as_string() if text is None else text
        project = Path(self.board.document.project.path) / self.board.document.project.name
        sidecars = {
            ext: (p.read_text(encoding="utf-8") if p.exists() else "")
            for ext in (".kicad_pro", ".kicad_dru")
            for p in [Path(str(project) + ext)]
        }
        classes = self.board.get_project().get_net_classes()
        class_data = sorted(c.proto.SerializeToString(deterministic=True).hex() for c in classes)
        return digest(
            {
                "document": self.initial_document.hex(),
                "source": text,
                "sidecars": sidecars,
                "netclasses": class_data,
            }
        )

    def assert_current(self, fingerprint):
        if self.identity() != fingerprint:
            raise RuntimeError(
                "Board or project rules changed. Capture a fresh board and regenerate/retest the plan."
            )

    def save_backup(self):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        folder = self.board_path.parent / "kicad-astra-backups" / stamp
        folder.mkdir(parents=True, exist_ok=False)
        target = folder / self.board_path.name
        self.save_copy(target)
        return target

    def save_copy(self, target):
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.board.save_as(str(target), overwrite=False, include_project=True)
        custom = Path(self.board.document.project.path) / (
            self.board.document.project.name + ".kicad_dru"
        )
        if custom.exists():
            target.with_suffix(".kicad_dru").write_bytes(custom.read_bytes())
        if not target.is_file():
            raise RuntimeError("KiCad did not write the requested board copy.")

    def capture(self):
        with self.lock:
            self.refresh()
            source = self.board.get_as_string()
            before = self.identity(source)
            state = read_scene(self.board, self.kicad)
            if self.identity() != before:
                raise RuntimeError("The board changed while it was being read. Capture it again.")
            return BoardSnapshot(state, source, before, self.board_path)

    def summary(self):
        return self.capture().state


def read_scene(board, kicad):
    from kipy.board_types import ArcTrack, BoardLayer, Field, PadType, to_concrete_board_shape
    from kipy.geometry import PolygonWithHoles
    from kipy.proto.board import board_commands_pb2 as commands
    from kipy.util.board_layer import is_copper_layer

    errors, warnings = [], []
    layer_ids = [layer for layer in board.get_enabled_layers() if is_copper_layer(layer)]

    def lname(layer):
        return BoardLayer.Name(layer).removeprefix("BL_").replace("_", ".", 1)

    layers = {layer: lname(layer) for layer in layer_ids}
    footprints = list(board.get_footprints())
    pads = list(board.get_pads())
    tracks, vias, zones = list(board.get_tracks()), list(board.get_vias()), list(board.get_zones())
    all_shapes = [to_concrete_board_shape(s) for s in board.get_shapes()]
    graphics = [*board.get_text(), *board.get_dimensions(), *board.get_barcodes()]
    graphic_owners = {}
    for fp in footprints:
        ref = fp.reference_field.text.value
        all_shapes.extend(fp.definition.shapes)
        zones.extend(i for i in fp.definition.items if type(i).__name__ == "Zone")
        fields = [fp.reference_field, fp.value_field, fp.datasheet_field, fp.description_field]
        texts = [i.text if isinstance(i, Field) else i for i in [*fp.definition.texts, *fields]]
        children = [*fp.definition.shapes, *texts]
        for child in children:
            if child.id.value:
                graphic_owners[child.id.value] = ref
        graphics.extend(texts)

    # Some server versions include footprint children in board-wide responses.
    # Repeated outlines must not cancel when composing even/odd board regions.
    def unique(items):
        seen = set()
        for item in items:
            key = item.id.value
            if not key:
                if getattr(item, "layer", None) in layers:
                    errors.append("Copper graphic has no stable KiCad identifier.")
                continue
            if key not in seen:
                seen.add(key)
                yield item

    all_shapes = list(unique(all_shapes))
    zones = list(unique(zones))

    outline_lines = []
    for item in all_shapes:
        if item.layer == BoardLayer.BL_Edge_Cuts:
            try:
                outline_lines.extend(shape_lines(item))
            except ValueError as exc:
                errors.append(str(exc))
    try:
        outline = encode(closed_region(outline_lines))
    except ValueError as exc:
        outline = None
        errors.append(str(exc))

    nets = list(board.get_nets())
    try:
        netclasses = board.get_netclass_for_nets(nets)
    except Exception as exc:
        netclasses = {}
        errors.append(f"Effective net classes unavailable: {exc}")
    net_rows = []
    for net in nets:
        row = {"name": net.name}
        nc = netclasses.get(net.name)
        if nc:
            row["class"] = nc.name
            for key in (
                "clearance",
                "track_width",
                "via_diameter",
                "via_drill",
                "diff_pair_track_width",
                "diff_pair_gap",
            ):
                value = getattr(nc, key, None)
                if value is not None:
                    row[key + "_mm"] = value / 1e6
        net_rows.append(row)

    pad_shapes = {p.id.value: {} for p in pads}
    for layer in layer_ids:
        # The kipy 0.8 convenience list omits absent pads; map explicit response IDs.
        for start in range(0, len(pads), 200):
            batch = pads[start : start + 200]
            cmd = commands.GetPadShapeAsPolygon()
            cmd.board.CopyFrom(board.document)
            cmd.layer = layer
            cmd.pads.extend(p.id for p in batch)
            response = board.client.send(cmd, commands.PadShapeAsPolygonResponse)
            if len(response.pads) != len(response.polygons):
                raise RuntimeError("KiCad returned mismatched pad geometry identifiers.")
            for uid, poly in zip(response.pads, response.polygons):
                if uid.value not in pad_shapes:
                    raise RuntimeError("KiCad returned an unrequested pad identifier.")
                g = from_kicad_polygon(PolygonWithHoles(poly))
                if not g.is_empty:
                    pad_shapes[uid.value][layers[layer]] = encode(g)

    owners = {
        p.id.value: fp.reference_field.text.value for fp in footprints for p in fp.definition.pads
    }
    pad_rows, holes, copper = [], [], []
    for pad in pads:
        ref = owners.get(pad.id.value, "")
        if not ref:
            errors.append(f"Pad {pad.id.value} has no footprint association.")
        row = {
            "id": pad.id.value,
            "reference": ref,
            "number": pad.number,
            "label": f"{ref}.{pad.number}",
            "net": pad.net.name,
            "position_mm": xy(pad.position),
            "layers": pad_shapes[pad.id.value],
            "type": PadType.Name(pad.pad_type),
        }
        pad_rows.append(row)
        for layer, g in row["layers"].items():
            copper.append(
                {
                    "id": pad.id.value,
                    "kind": "pad",
                    "owner": ref,
                    "net": pad.net.name,
                    "layer": layer,
                    "geometry": g,
                }
            )
        if not row["layers"] and pad.pad_type != PadType.PT_NPTH:
            errors.append(f"Copper geometry missing for {row['label']}.")
        drill = pad.padstack.drill.diameter
        if max(drill.x, drill.y) > 0:
            # A circumscribed disk is conservative for slotted drills.
            radius = max(drill.x, drill.y) / 2e6
            holes.append(
                {
                    "id": pad.id.value,
                    "owner": ref,
                    "net": pad.net.name if pad.pad_type == PadType.PT_PTH else "",
                    "geometry": encode(Point(xy(pad.position)).buffer(radius)),
                }
            )

    fp_rows, group_members = [], set()
    for group in board.get_groups():
        group_members.update(uid.value for uid in group.proto.items)
    movable_types = {
        "Pad",
        "BoardText",
        "Field",
        "BoardShape",
        "BoardSegment",
        "BoardArc",
        "BoardCircle",
        "BoardRectangle",
        "BoardPolygon",
        "BoardBezier",
        "Footprint3DModel",
    }
    for fp in footprints:
        ref = fp.reference_field.text.value
        side = "front" if fp.layer == BoardLayer.BL_F_Cu else "back"
        courts = {}
        for layer, side_name in ((BoardLayer.BL_F_CrtYd, "front"), (BoardLayer.BL_B_CrtYd, "back")):
            lines = []
            try:
                for item in fp.definition.shapes:
                    if item.layer == layer:
                        lines.extend(shape_lines(item))
                if lines:
                    courts[side_name] = encode(closed_region(lines))
            except ValueError as exc:
                errors.append(f"{ref} courtyard: {exc}")
        fallback = False
        if not courts:
            bb = board.get_item_bounding_box(fp, include_text=False)
            if bb:
                x, y = xy(bb.pos)
                sx, sy = xy(bb.size)
                courts[side] = encode(box(x, y, x + sx, y + sy))
                fallback = True
                warnings.append(f"{ref}: missing courtyard; using conservative KiCad bounding box.")
            else:
                errors.append(f"{ref}: no usable body/courtyard geometry.")
        unsupported = [
            type(i).__name__ for i in fp.definition.items if type(i).__name__ not in movable_types
        ]
        fp_rows.append(
            {
                "id": fp.id.value,
                "reference": ref,
                "value": fp.value_field.text.value,
                "position_mm": xy(fp.position),
                "rotation_deg": fp.orientation.degrees,
                "side": side,
                "locked": fp.locked,
                "grouped": fp.id.value in group_members,
                "courtyards": courts,
                "conservative_body": fallback,
                "unsupported_children": unsupported,
            }
        )

    for track in tracks:
        points = (
            arc_points(xy(track.start), xy(track.mid), xy(track.end))
            if isinstance(track, ArcTrack)
            else [xy(track.start), xy(track.end)]
        )
        copper.append(
            {
                "id": track.id.value,
                "kind": "track",
                "owner": "",
                "net": track.net.name,
                "layer": layers[track.layer],
                "geometry": encode(LineString(points).buffer(track.width / 2e6 + CURVE_ERROR_MM)),
                "points_mm": points,
                "width_mm": track.width / 1e6,
            }
        )
    for via in vias:
        diameter = max(
            (max(layer.size.x, layer.size.y) / 1e6 for layer in via.padstack.copper_layers),
            default=0,
        )
        if diameter <= 0:
            errors.append(f"Via {via.id.value} has no usable padstack.")
        g = Point(xy(via.position)).buffer(diameter / 2)
        for layer in layers.values():
            copper.append(
                {
                    "id": via.id.value,
                    "kind": "via",
                    "owner": "",
                    "net": via.net.name,
                    "layer": layer,
                    "geometry": encode(g),
                }
            )
        holes.append(
            {
                "id": via.id.value,
                "owner": "",
                "net": via.net.name,
                "geometry": encode(Point(xy(via.position)).buffer(via.drill_diameter / 2e6)),
            }
        )

    keepouts = []
    for zone in zones:
        outer = unary_union(
            [from_kicad_polygon(PolygonWithHoles(p)) for p in zone.proto.outline.polygons]
        )
        if zone.is_rule_area():
            r = zone.proto.rule_area_settings
            keepouts.append(
                {
                    "id": zone.id.value,
                    "layers": [layers[layer] for layer in zone.layers if layer in layers],
                    "geometry": encode(outer),
                    "tracks": r.keepout_tracks,
                    "vias": r.keepout_vias,
                    "pads": r.keepout_pads,
                    "footprints": r.keepout_footprints,
                }
            )
        else:
            for layer in zone.layers:
                if layer in layers:
                    # Full zone outlines also cover unfilled/stale pours; conservative obstacles.
                    copper.append(
                        {
                            "id": zone.id.value,
                            "kind": "zone",
                            "owner": "",
                            "net": zone.net.name,
                            "layer": layers[layer],
                            "geometry": encode(outer),
                        }
                    )
    for item in unique([*all_shapes, *graphics]):
        if getattr(item, "layer", None) in layers:
            bb = board.get_item_bounding_box(item, include_text=True)
            if bb:
                x, y = xy(bb.pos)
                w, h = xy(bb.size)
                copper.append(
                    {
                        "id": item.id.value,
                        "kind": "graphic",
                        "owner": graphic_owners.get(item.id.value, ""),
                        "net": "",
                        "layer": layers[item.layer],
                        "geometry": encode(box(x, y, x + w, y + h)),
                    }
                )
            else:
                errors.append("Unresolved drawing/text on a copper layer.")
    project_path = Path(board.document.project.path) / (board.document.project.name + ".kicad_pro")
    project_rules = {}
    if project_path.exists():
        project_rules = (
            json.loads(project_path.read_text(encoding="utf-8"))
            .get("board", {})
            .get("design_settings", {})
            .get("rules", {})
        )
    from kicad.labels import capture_silkscreen

    silk, silk_errors = capture_silkscreen(board, footprints, unique([*all_shapes, *graphics]))
    return {
        "silkscreen": silk,
        "silkscreen_errors": silk_errors,
        "format_version": 2,
        "units": "mm",
        "board_file": board.name,
        "kicad_version": str(kicad.get_version()),
        "curve_tolerance_mm": CURVE_ERROR_MM,
        "outline": outline,
        "copper_layers": list(layers.values()),
        "footprints": fp_rows,
        "pads": pad_rows,
        "nets": net_rows,
        "copper": copper,
        "holes": holes,
        "keepouts": keepouts,
        "project_rules": project_rules,
        "geometry_errors": errors,
        "warnings": warnings,
        "counts": {
            "footprints": len(footprints),
            "pads": len(pads),
            "nets": len(nets),
            "track_segments": len(tracks),
            "vias": len(vias),
            "zones": len(zones),
        },
    }
