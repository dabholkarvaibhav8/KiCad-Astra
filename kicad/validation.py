"""Deterministic geometry and connectivity checks. KiCad DRC is a separate gate."""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field

from shapely.geometry import LineString, Point, Polygon

from agent.tools import PlanFormatError, normalize_plan
from kicad.config import LayoutRules
from kicad.geometry import CURVE_ERROR_MM, EPS, capsule, decode, encode, filled_outer, move_geometry


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.errors

    def as_text(self):
        return "\n".join(
            [
                "LOCAL CHECKS PASSED" if self.ok else "BLOCKED",
                *["ERROR: " + s for s in self.errors],
                *["NOTE: " + s for s in self.warnings],
                *[f"{k}: {v}" for k, v in self.metrics.items()],
            ]
        )

    def to_dict(self):
        return {**asdict(self), "ok": self.ok}


def net_rule(state, net, key, default):
    row = next((n for n in state["nets"] if n["name"] == net), {})
    value = row.get(key, default)
    return max(default, float(value or default))


def project_min(state, key, default):
    value = state.get("project_rules", {}).get(key, default)
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return max(default, value)


def clearance(state, rules, a, b=""):
    base = project_min(state, "min_clearance", rules.clearance_mm)
    return max(net_rule(state, a, "clearance_mm", base), net_rule(state, b, "clearance_mm", base))


def route_dimensions(state, rules, net):
    width = net_rule(
        state, net, "track_width_mm", project_min(state, "min_track_width", rules.track_width_mm)
    )
    drill = net_rule(
        state,
        net,
        "via_drill_mm",
        project_min(state, "min_through_hole_diameter", rules.via_drill_mm),
    )
    annular = project_min(state, "min_via_annular_width", rules.annular_ring_mm)
    diameter = net_rule(
        state, net, "via_diameter_mm", project_min(state, "min_via_diameter", rules.via_diameter_mm)
    )
    return width, max(diameter, drill + 2 * annular), drill


def projected_scene(state, placements):
    result = copy.deepcopy(state)
    by_ref = {fp["reference"]: fp for fp in result["footprints"]}
    for op in placements:
        fp = by_ref[op["reference"]]
        old_xy, old_angle = fp["position_mm"], fp["rotation_deg"]
        new_xy = (op["x_mm"], op["y_mm"])

        def transform(value):
            return encode(
                move_geometry(decode(value), old_xy, old_angle, new_xy, op["rotation_deg"])
            )

        fp["courtyards"] = {s: transform(g) for s, g in fp["courtyards"].items()}
        for pad in result["pads"]:
            if pad["reference"] == op["reference"]:
                p = move_geometry(
                    Point(pad["position_mm"]), old_xy, old_angle, new_xy, op["rotation_deg"]
                )
                pad["position_mm"] = (p.x, p.y)
                pad["layers"] = {layer: transform(g) for layer, g in pad["layers"].items()}
        for item in result["copper"] + result["holes"]:
            if item.get("owner") == op["reference"]:
                item["geometry"] = transform(item["geometry"])
        fp["position_mm"] = new_xy
        fp["rotation_deg"] = op["rotation_deg"]
    return result


def hpwl(state):
    # A placement proxy, not routed wire length or signal-integrity quality.
    nets = {}
    for p in state["pads"]:
        if p["net"]:
            nets.setdefault(p["net"], []).append(p["position_mm"])
    return round(
        sum(
            max(x for x, y in pts)
            - min(x for x, y in pts)
            + max(y for x, y in pts)
            - min(y for x, y in pts)
            for pts in nets.values()
            if len(pts) > 1
        ),
        4,
    )


def validate_placements(plan, state, rules):
    report = ValidationReport()
    by_ref = {f["reference"]: f for f in state["footprints"]}
    if len(by_ref) != len(state["footprints"]):
        report.errors.append("Footprint references are duplicated; annotate the board first.")
    moved = set()
    for op in plan["placements"]:
        ref = op["reference"]
        fp = by_ref.get(ref)
        if fp is None:
            report.errors.append(f"Unknown footprint {ref}.")
            continue
        if ref in moved:
            report.errors.append(f"Duplicate placement for {ref}.")
        moved.add(ref)
        if fp["locked"] or rules.fixed(ref):
            report.errors.append(f"{ref} is locked or fixed by constraints.")
        if fp.get("grouped"):
            report.errors.append(f"{ref} belongs to a group; move it with KiCad's group tools.")
        if fp.get("unsupported_children"):
            report.errors.append(
                f"{ref} contains unsupported movable children: {fp['unsupported_children']}."
            )
        if op["side"] != fp["side"]:
            report.errors.append(
                f"{ref}: side changes require a separate KiCad operation and fresh snapshot."
            )
        if math.dist(fp["position_mm"], (op["x_mm"], op["y_mm"])) > rules.max_move_mm:
            report.errors.append(f"{ref} exceeds max_move_mm.")
        if (
            math.dist(fp["position_mm"], (op["x_mm"], op["y_mm"])) < EPS
            and abs((op["rotation_deg"] - fp["rotation_deg"]) % 360) < EPS
        ):
            report.errors.append(f"{ref} placement is a no-op.")
        # Moving attached pads would leave the existing routed copper behind.
        for pad in (p for p in state["copper"] if p.get("owner") == ref and p["kind"] == "pad"):
            for item in state["copper"]:
                if (
                    item["kind"] in {"track", "via"}
                    and item["layer"] == pad["layer"]
                    and item["net"] == pad["net"]
                    and decode(pad["geometry"]).distance(decode(item["geometry"])) <= CURVE_ERROR_MM
                ):
                    report.errors.append(
                        f"{ref} is attached to existing copper; rerouting is needed before moving it."
                    )
                    break
    if report.errors:
        return report, state
    result = projected_scene(state, plan["placements"])
    if not moved:
        return report, result
    outline = decode(state["outline"]).buffer(
        -project_min(state, "copper_edge_clearance", rules.edge_clearance_mm) - CURVE_ERROR_MM
    )
    fps = result["footprints"]
    for i, fp in enumerate(fps):
        ref = fp["reference"]
        for side, value in fp["courtyards"].items():
            body = decode(value)
            if ref in moved:
                if not outline.covers(body):
                    report.errors.append(
                        f"{ref} body/courtyard crosses the board boundary or a cutout."
                    )
                if ref in rules.placement_regions and not Polygon(
                    rules.placement_regions[ref]
                ).covers(body):
                    report.errors.append(f"{ref} is outside its permitted placement region.")
                for k in state["keepouts"]:
                    layer = "F.Cu" if side == "front" else "B.Cu"
                    if (
                        k["footprints"]
                        and (not k["layers"] or layer in k["layers"])
                        and body.intersects(decode(k["geometry"]))
                    ):
                        report.errors.append(f"{ref} overlaps footprint keepout {k['id']}.")
            for other in fps[i + 1 :]:
                if (
                    (ref in moved or other["reference"] in moved)
                    and side in other["courtyards"]
                    and body.distance(decode(other["courtyards"][side]))
                    < rules.courtyard_clearance_mm - EPS
                ):
                    report.errors.append(
                        f"Courtyard collision: {ref} / {other['reference']} on {side}."
                    )
    for pad in (c for c in result["copper"] if c.get("owner") in moved):
        pg = decode(pad["geometry"])
        if not outline.covers(pg):
            report.errors.append(f"Copper on {pad['owner']} crosses the board edge/cutout.")
        for other in result["copper"]:
            if (
                other["id"] == pad["id"]
                or other["layer"] != pad["layer"]
                or (pad["net"] and other["net"] == pad["net"])
            ):
                continue
            if (
                pg.distance(decode(other["geometry"]))
                < clearance(state, rules, pad["net"], other["net"]) + CURVE_ERROR_MM - EPS
            ):
                report.errors.append(
                    f"Copper clearance: {pad['owner']} {pad['kind']} / {other['kind']} {other['id']}."
                )
        for hole in result["holes"]:
            if hole["id"] == pad["id"] or (pad["net"] and hole["net"] == pad["net"]):
                continue
            if (
                pg.distance(decode(hole["geometry"]))
                < project_min(state, "min_hole_clearance", rules.hole_clearance_mm)
                + CURVE_ERROR_MM
                - EPS
            ):
                report.errors.append(
                    f"Copper on {pad['owner']} is too close to drill hole {hole['id']}."
                )
        for keepout in result["keepouts"]:
            if (
                pad["kind"] == "pad"
                and keepout["pads"]
                and (not keepout["layers"] or pad["layer"] in keepout["layers"])
                and pg.intersects(decode(keepout["geometry"]))
            ):
                report.errors.append(f"Pad on {pad['owner']} enters a pad keepout.")
    for hole in (h for h in result["holes"] if h.get("owner") in moved):
        hg = decode(hole["geometry"])
        if not outline.covers(hg):
            report.errors.append(f"Drill on {hole['owner']} crosses the board edge/cutout.")
        for other in result["holes"]:
            if (
                hole["id"] != other["id"]
                and hg.distance(decode(other["geometry"]))
                < project_min(state, "min_hole_to_hole", rules.hole_clearance_mm) - EPS
            ):
                report.errors.append(f"Drill on {hole['owner']} conflicts with hole {other['id']}.")
        for other in result["copper"]:
            if hole["id"] == other["id"] or (hole["net"] and hole["net"] == other["net"]):
                continue
            if (
                hg.distance(decode(other["geometry"]))
                < project_min(state, "min_hole_clearance", rules.hole_clearance_mm)
                + CURVE_ERROR_MM
                - EPS
            ):
                report.errors.append(
                    f"Drill on {hole['owner']} conflicts with copper {other['id']}."
                )
    for constraint in rules.proximity:
        a = [p for p in result["pads"] if p["label"] == constraint["a"]]
        b = [p for p in result["pads"] if p["label"] == constraint["b"]]
        if not a or not b:
            report.errors.append(f"Unknown proximity pad label: {constraint}.")
            continue
        distance = min(math.dist(x["position_mm"], y["position_mm"]) for x in a for y in b)
        if distance > constraint["max_mm"]:
            report.errors.append(
                f"{constraint['a']} to {constraint['b']}: {distance:.3f} mm exceeds {constraint['max_mm']} mm."
            )
    report.metrics = {
        "estimated_net_span_before_mm": hpwl(state),
        "estimated_net_span_after_mm": hpwl(result),
    }
    return report, result


def copper_items(route):
    items = []
    for i, s in enumerate(route["segments"]):
        items.append(
            {
                "id": f"{route['id']}:s{i}",
                "kind": "track",
                "owner": "",
                "net": route["net"],
                "layer": s["layer"],
                "geometry": encode(capsule(s["points_mm"], s["width_mm"])),
            }
        )
    for i, v in enumerate(route["vias"]):
        for layer in route["board_layers"]:
            items.append(
                {
                    "id": f"{route['id']}:v{i}",
                    "kind": "via",
                    "owner": "",
                    "net": route["net"],
                    "layer": layer,
                    "geometry": encode(Point(v["position_mm"]).buffer(v["diameter_mm"] / 2)),
                }
            )
    return items


def validate_routes(routes, state, rules, report):
    pads = {p["id"]: p for p in state["pads"]}
    staged = list(state["copper"])
    holes = list(state["holes"])
    edge = decode(state["outline"]).buffer(
        -project_min(state, "copper_edge_clearance", rules.edge_clearance_mm) - CURVE_ERROR_MM
    )
    length = 0
    via_count = 0
    for route in routes:
        net = route["net"]
        a, b = pads.get(route["from_pad_id"]), pads.get(route["to_pad_id"])
        if not a or not b or not net or a["net"] != net or b["net"] != net or a["id"] == b["id"]:
            report.errors.append("Route endpoints do not identify distinct pads on the named net.")
            continue
        if net in rules.manual_nets:
            report.errors.append(f"{net} is reserved for manual routing.")
        width, diameter, drill = route_dimensions(state, rules, net)
        segs = route["segments"]
        vias = route["vias"]
        if not segs or len(segs) > 128 or len(vias) > 32:
            report.errors.append(f"{net}: invalid or excessive route primitives.")
            continue
        for i, s in enumerate(segs):
            pts = s["points_mm"]
            if s["layer"] not in rules.allowed_layers or s["layer"] not in state["copper_layers"]:
                report.errors.append(f"{net}: disallowed layer {s['layer']}.")
            if not math.isfinite(s["width_mm"]) or s["width_mm"] < width - EPS:
                report.errors.append(f"{net}: width is below the effective routing width.")
            if len(pts) < 2 or any(
                len(p) != 2 or any(not math.isfinite(v) for v in p) for p in pts
            ):
                report.errors.append(f"{net}: invalid route coordinates.")
                continue
            if any(math.dist(p, q) < EPS for p, q in zip(pts, pts[1:])):
                report.errors.append(f"{net}: zero-length segment.")
            length += LineString(pts).length
            if i and math.dist(segs[i - 1]["points_mm"][-1], pts[0]) > EPS:
                report.errors.append(f"{net}: disconnected consecutive route sections.")
            if (
                i
                and segs[i - 1]["layer"] != s["layer"]
                and not any(math.dist(v["position_mm"], pts[0]) < EPS for v in vias)
            ):
                report.errors.append(f"{net}: layer transition has no via.")
        first, last = segs[0], segs[-1]
        for pad, s, pt in ((a, first, first["points_mm"][0]), (b, last, last["points_mm"][-1])):
            if s["layer"] not in pad["layers"] or not filled_outer(
                decode(pad["layers"][s["layer"]])
            ).buffer(EPS).covers(Point(pt)):
                report.errors.append(f"{net}: endpoint misses pad {pad['label']} on {s['layer']}.")
        if vias and not rules.allow_vias:
            report.errors.append("Through-vias are disabled in constraints.")
        for v in vias:
            via_count += 1
            if (
                v["diameter_mm"] < diameter - EPS
                or v["drill_mm"] < drill - EPS
                or (v["diameter_mm"] - v["drill_mm"]) / 2 < rules.annular_ring_mm - EPS
            ):
                report.errors.append(f"{net}: invalid via diameter/drill/annular ring.")
            if not any(
                i
                and segs[i - 1]["layer"] != s["layer"]
                and math.dist(v["position_mm"], s["points_mm"][0]) < EPS
                for i, s in enumerate(segs)
            ):
                report.errors.append(f"{net}: unattached via.")
            hole = Point(v["position_mm"]).buffer(v["drill_mm"] / 2)
            for other in holes:
                if (
                    hole.distance(decode(other["geometry"]))
                    < project_min(state, "min_hole_to_hole", rules.hole_clearance_mm) - EPS
                ):
                    report.errors.append(f"{net}: via drill conflicts with another hole.")
            holes.append({"geometry": encode(hole), "net": net})
        items = copper_items(route)
        for item in items:
            g = decode(item["geometry"])
            if not edge.covers(g):
                report.errors.append(f"{net}: copper crosses board edge/cutout.")
            for other in staged:
                if item["layer"] != other["layer"] or (net and net == other["net"]):
                    continue
                if (
                    g.distance(decode(other["geometry"]))
                    < clearance(state, rules, net, other["net"]) + CURVE_ERROR_MM - EPS
                ):
                    report.errors.append(
                        f"{net}: copper clearance to {other['net'] or other['kind']} ({other['id']})."
                    )
            for h in state["holes"]:
                if h["net"] == net:
                    continue
                if (
                    g.distance(decode(h["geometry"]))
                    < project_min(state, "min_hole_clearance", rules.hole_clearance_mm)
                    + CURVE_ERROR_MM
                    - EPS
                ):
                    report.errors.append(f"{net}: copper too close to a drill hole.")
            for keep in state["keepouts"]:
                flag = keep["vias"] if item["kind"] == "via" else keep["tracks"]
                if (
                    flag
                    and (not keep["layers"] or item["layer"] in keep["layers"])
                    and g.intersects(decode(keep["geometry"]))
                ):
                    report.errors.append(f"{net}: copper enters a keepout.")
        staged.extend(items)
    report.metrics.update(
        {
            "proposed_trace_length_mm": round(length, 4),
            "proposed_vias": via_count,
            "proposed_connections": len(routes),
        }
    )


def validate_plan(plan, board, rules=None, routes=None):
    rules = (rules or LayoutRules()).checked()
    report = ValidationReport()
    try:
        plan = normalize_plan(plan)
    except PlanFormatError as exc:
        report.errors.append(str(exc))
        return report
    if not plan["placements"] and not plan["connections"] and not routes:
        report.warnings.extend(board.get("geometry_errors", []))
        return report
    if not board.get("outline") or board.get("geometry_errors"):
        report.errors.extend(board.get("geometry_errors", []) or ["No valid closed board outline."])
        return report
    report, state = validate_placements(plan, board, rules)
    if report.ok and routes is not None:
        validate_routes(routes, state, rules, report)
    report.errors = list(dict.fromkeys(report.errors))
    report.warnings.extend(board.get("warnings", []))
    if plan["connections"] and routes is None:
        report.warnings.append("Connection intents still require local route compilation.")
    return report
