"""Bounded multi-layer A*: exact collision tests, real pad endpoints, through-vias."""

from __future__ import annotations

import copy
import heapq
import itertools
import math
import time
from uuid import NAMESPACE_URL, uuid5

from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.prepared import prep

from kicad.geometry import CURVE_ERROR_MM, EPS, decode, encode, filled_outer
from kicad.validation import clearance, copper_items, project_min, route_dimensions

DIRECTIONS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


class RoutingError(ValueError):
    pass


def pad_anchor(pad, layer):
    geometry = filled_outer(decode(pad["layers"][layer]))
    center = Point(pad["position_mm"])
    point = center if geometry.covers(center) else geometry.representative_point()
    return (point.x, point.y)


class RoutingSpace:
    def __init__(self, state, rules, net, width, diameter, drill, layers):
        self.state, self.rules, self.net = state, rules, net
        self.layers = layers
        self.track = {}
        self.via = {}
        self.edge = decode(state["outline"])
        edge_clear = (
            project_min(state, "copper_edge_clearance", rules.edge_clearance_mm) + CURVE_ERROR_MM
        )
        self.track_board = prep(self.edge.buffer(-edge_clear - width / 2))
        self.via_board = prep(self.edge.buffer(-edge_clear - diameter / 2))
        for layer in state["copper_layers"]:
            track_obs = []
            via_obs = []
            for item in state["copper"]:
                if item["layer"] != layer or (net and item["net"] == net):
                    continue
                amount = clearance(state, rules, net, item["net"]) + CURVE_ERROR_MM
                geometry = decode(item["geometry"])
                track_obs.append(geometry.buffer(amount + width / 2))
                via_obs.append(geometry.buffer(amount + diameter / 2))
            for hole in state["holes"]:
                geometry = decode(hole["geometry"])
                via_obs.append(
                    geometry.buffer(
                        drill / 2
                        + project_min(state, "min_hole_to_hole", rules.hole_clearance_mm)
                        + CURVE_ERROR_MM
                    )
                )
                if hole["net"] != net:
                    amount = (
                        project_min(state, "min_hole_clearance", rules.hole_clearance_mm)
                        + CURVE_ERROR_MM
                    )
                    track_obs.append(geometry.buffer(amount + width / 2))
                    via_obs.append(geometry.buffer(amount + diameter / 2))
            for area in state["keepouts"]:
                if area["layers"] and layer not in area["layers"]:
                    continue
                geometry = decode(area["geometry"])
                if area["tracks"]:
                    track_obs.append(geometry.buffer(width / 2 + CURVE_ERROR_MM))
                if area["vias"]:
                    via_obs.append(geometry.buffer(diameter / 2 + CURVE_ERROR_MM))
            self.track[layer] = prep(unary_union(track_obs))
            self.via[layer] = prep(unary_union(via_obs))
        self.edges = {}
        self.via_cache = {}

    def segment_free(self, a, b, layer):
        key = (tuple(a), tuple(b), layer)
        if key not in self.edges:
            geometry = Point(a) if a == b else LineString([a, b])
            self.edges[key] = self.track_board.covers(geometry) and not self.track[
                layer
            ].intersects(geometry)
        return self.edges[key]

    def via_free(self, p):
        if p not in self.via_cache:
            point = Point(p)
            # Through-vias cross every board copper layer, not just requested routing layers.
            self.via_cache[p] = self.via_board.covers(point) and all(
                not obs.intersects(point) for obs in self.via.values()
            )
        return self.via_cache[p]


def simplify(points):
    result = []
    for p in points:
        p = [round(p[0], 6), round(p[1], 6)]
        if result and math.dist(p, result[-1]) < EPS:
            continue
        while len(result) > 1:
            a, b = result[-2:]
            if abs((b[0] - a[0]) * (p[1] - b[1]) - (b[1] - a[1]) * (p[0] - b[0])) > 1e-8:
                break
            result.pop()
        result.append(p)
    return result


def route_connection(connection, state, rules, *, seed="", cancel=None):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Routing cancelled.")
    rules.checked()
    pads = {p["id"]: p for p in state["pads"]}
    a = pads.get(connection["from_pad_id"])
    b = pads.get(connection["to_pad_id"])
    net = connection["net"]
    if not a or not b or a["id"] == b["id"] or not net or a["net"] != net or b["net"] != net:
        raise RoutingError("Connection must reference two real pads on the same nonempty net.")
    if net in rules.manual_nets:
        raise RoutingError(f"{net} is assigned to manual routing.")
    layers = list(dict.fromkeys(connection["layers"]))
    if not layers or any(
        layer not in state["copper_layers"] or layer not in rules.allowed_layers for layer in layers
    ):
        raise RoutingError("Connection requested an unavailable or disallowed copper layer.")
    if not rules.allow_vias:
        layers = [layer for layer in layers if layer in a["layers"] and layer in b["layers"]]
    starts = {layer: pad_anchor(a, layer) for layer in layers if layer in a["layers"]}
    targets = {layer: pad_anchor(b, layer) for layer in layers if layer in b["layers"]}
    if not starts or not targets:
        raise RoutingError("Pads have no compatible routing layers under the current via setting.")
    width, diameter, drill = route_dimensions(state, rules, net)
    space = RoutingSpace(state, rules, net, width, diameter, drill, layers)
    route_id = str(uuid5(NAMESPACE_URL, seed + net + a["id"] + b["id"]))
    base = {
        "id": route_id,
        "net": net,
        "from_pad_id": a["id"],
        "to_pad_id": b["id"],
        "board_layers": state["copper_layers"],
        "segments": [],
        "vias": [],
        "search_nodes": 0,
    }
    for layer in (layer for layer in layers if layer in starts and layer in targets):
        if math.dist(starts[layer], targets[layer]) > EPS and space.segment_free(
            starts[layer], targets[layer], layer
        ):
            dx = abs(starts[layer][0] - targets[layer][0])
            dy = abs(starts[layer][1] - targets[layer][1])
            if min(dx, dy) < EPS or abs(dx - dy) < EPS:
                base["segments"] = [
                    {
                        "layer": layer,
                        "points_mm": simplify([starts[layer], targets[layer]]),
                        "width_mm": width,
                    }
                ]
                return base

    grid = rules.grid_mm

    def world(node):
        return (round(node[0] * grid, 6), round(node[1] * grid, 6))

    def heuristic(node):
        return min(math.dist(world(node), p) for p in targets.values())

    queue = []
    serial = itertools.count()
    cost = {}
    parent = {}
    origins = {}
    for layer, p in starts.items():
        cx, cy = round(p[0] / grid), round(p[1] / grid)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                node = (cx + dx, cy + dy, layer, 8)
                if space.segment_free(p, world(node), layer):
                    cost[node] = math.dist(p, world(node))
                    parent[node] = None
                    origins[node] = p
                    heapq.heappush(
                        queue, (cost[node] + heuristic(node), next(serial), cost[node], node)
                    )
    deadline = time.monotonic() + rules.route_timeout_s
    count = 0
    finish = None
    while queue:
        _, _, current_cost, node = heapq.heappop(queue)
        if current_cost > cost[node] + EPS:
            continue
        count += 1
        if count % 128 == 0:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Routing cancelled.")
            if count > rules.max_search_nodes or time.monotonic() > deadline:
                break
        x, y, layer, heading = node
        p = world(node)
        if (
            layer in targets
            and math.dist(p, targets[layer]) <= 2 * grid
            and space.segment_free(p, targets[layer], layer)
        ):
            finish = node
            break
        neighbors = []
        for direction, (dx, dy) in enumerate(DIRECTIONS):
            other = (x + dx, y + dy, layer, direction)
            if space.segment_free(p, world(other), layer):
                bend = grid * 0.2 if heading != 8 and direction != heading else 0
                neighbors.append((other, math.hypot(dx, dy) * grid + bend))
        if rules.allow_vias and space.via_free(p):
            neighbors.extend(
                ((x, y, next_layer, 8), rules.via_cost_mm)
                for next_layer in layers
                if next_layer != layer
            )
        for other, step in neighbors:
            tentative = current_cost + step
            if tentative + EPS < cost.get(other, math.inf):
                cost[other] = tentative
                parent[other] = node
                heapq.heappush(
                    queue, (tentative + heuristic(other), next(serial), tentative, other)
                )
    if finish is None:
        raise RoutingError(
            f"No route found for {a['label']} → {b['label']} within the grid, {count:,}-node search and time budget. Adjust placement, width/grid or route manually."
        )
    chain = []
    node = finish
    while node is not None:
        chain.append(node)
        node = parent[node]
    chain.reverse()
    layer = chain[0][2]
    points = [origins[chain[0]], world(chain[0])]
    for node in chain[1:]:
        p = world(node)
        if node[2] != layer:
            cleaned = simplify(points)
            # A transition directly on a pad still needs a nonzero track section.
            if len(cleaned) < 2:
                raise RoutingError(
                    "A via at a pad centre is not supported; choose another grid or placement."
                )
            base["segments"].append({"layer": layer, "points_mm": cleaned, "width_mm": width})
            base["vias"].append(
                {"position_mm": list(p), "diameter_mm": diameter, "drill_mm": drill}
            )
            layer = node[2]
            points = [p]
        else:
            points.append(p)
    points.append(targets[layer])
    cleaned = simplify(points)
    if len(cleaned) < 2:
        raise RoutingError("Zero-length final route section.")
    base["segments"].append({"layer": layer, "points_mm": cleaned, "width_mm": width})
    base["search_nodes"] = count
    return base


def compile_connections(connections, state, rules, *, seed="", cancel=None, progress=None):
    if len(connections) > rules.max_connections:
        raise RoutingError(f"Limit this plan to {rules.max_connections} connections.")
    current = copy.deepcopy(state)
    routes = []
    errors = []
    seen = set()
    for index, connection in enumerate(connections):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Routing cancelled.")
        key = tuple(sorted((connection["from_pad_id"], connection["to_pad_id"])))
        if key in seen:
            errors.append("Duplicate pad pair in routing plan.")
            continue
        seen.add(key)
        if progress:
            progress(f"Routing connection {index + 1}/{len(connections)}…")
        try:
            route = route_connection(connection, current, rules, seed=seed, cancel=cancel)
        except RoutingError as exc:
            errors.append(str(exc))
            continue
        routes.append(route)
        current["copper"].extend(copper_items(route))
        for via in route["vias"]:
            current["holes"].append(
                {
                    "id": route["id"],
                    "owner": "",
                    "net": route["net"],
                    "geometry": encode(Point(via["position_mm"]).buffer(via["drill_mm"] / 2)),
                }
            )
    return routes, errors
