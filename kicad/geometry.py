"""Geometry in board millimetres. Curves are sampled with a bounded chord error."""

from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, Polygon, box, mapping, shape
from shapely.ops import polygonize_full, unary_union

CURVE_ERROR_MM = 0.005
EPS = 1e-6


def xy(point) -> tuple[float, float]:
    return (point.x / 1_000_000, point.y / 1_000_000)


def arc_points(start, mid, end, tolerance=CURVE_ERROR_MM):
    ax, ay = start
    bx, by = mid
    cx, cy = end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [start, mid, end]
    aa, bb, cc = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d
    uy = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d
    angles = [math.atan2(y - uy, x - ux) for x, y in (start, mid, end)]
    sweep = (angles[2] - angles[0]) % (2 * math.pi)
    if (angles[1] - angles[0]) % (2 * math.pi) > sweep:
        sweep -= 2 * math.pi
    radius = math.hypot(ax - ux, ay - uy)
    step = 2 * math.acos(max(-1, min(1, 1 - tolerance / max(radius, tolerance))))
    count = max(2, math.ceil(abs(sweep) / max(step, 1e-5)))
    return (
        [start]
        + [
            (
                ux + radius * math.cos(angles[0] + sweep * i / count),
                uy + radius * math.sin(angles[0] + sweep * i / count),
            )
            for i in range(1, count)
        ]
        + [end]
    )


def polyline_points(polyline):
    points = []
    for node in polyline.nodes:
        if node.has_point:
            points.append(xy(node.point))
        elif node.has_arc:
            points.extend(arc_points(xy(node.arc.start), xy(node.arc.mid), xy(node.arc.end)))
    return points


def from_kicad_polygon(poly):
    outer = polyline_points(poly.outline)
    if len(outer) < 3:
        return GeometryCollection()
    holes = [p for h in poly.holes if len(p := polyline_points(h)) >= 3]
    result = Polygon(outer, holes)
    if not result.is_valid:
        raise ValueError("KiCad returned invalid polygon geometry.")
    return result


def shape_lines(item):
    """Returns closed/open centre-lines; unsupported outline types fail closed."""
    from kipy.board_types import BoardArc, BoardCircle, BoardPolygon, BoardRectangle, BoardSegment

    if isinstance(item, BoardSegment):
        return [LineString([xy(item.start), xy(item.end)])]
    if isinstance(item, BoardArc):
        return [LineString(arc_points(xy(item.start), xy(item.mid), xy(item.end)))]
    if isinstance(item, BoardCircle):
        center = xy(item.center)
        radius = math.dist(center, xy(item.radius_point))
        count = max(
            32,
            math.ceil(
                math.pi
                / math.acos(max(-1, min(1, 1 - CURVE_ERROR_MM / max(radius, CURVE_ERROR_MM))))
            ),
        )
        points = [
            (
                center[0] + radius * math.cos(2 * math.pi * i / count),
                center[1] + radius * math.sin(2 * math.pi * i / count),
            )
            for i in range(count)
        ]
        return [LineString(points + [points[0]])]
    if isinstance(item, BoardRectangle):
        a, b = xy(item.top_left), xy(item.bottom_right)
        return [box(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])).exterior]
    if isinstance(item, BoardPolygon):
        lines = []
        for poly in item.polygons:
            g = from_kicad_polygon(poly)
            if not g.is_empty:
                lines.extend([g.exterior, *g.interiors])
        return lines
    raise ValueError(f"Unsupported outline shape: {type(item).__name__}")


def closed_region(lines):
    """Build concave/disjoint boards with nested cutouts via even/odd fill."""
    if not lines:
        raise ValueError("No closed outline was found.")
    polygons, cuts, dangles, invalid = polygonize_full(unary_union(lines))
    if not cuts.is_empty or not dangles.is_empty or not invalid.is_empty:
        raise ValueError("Outline contains gaps, branches, or self-intersections.")
    rings = {}
    for poly in polygons.geoms:
        for ring in [poly.exterior, *poly.interiors]:
            r = Polygon(ring)
            rings[r.normalize().wkb] = r
    result = GeometryCollection()
    for ring in rings.values():
        result = result.symmetric_difference(ring)
    if result.is_empty or not result.is_valid:
        raise ValueError("Outline does not enclose a valid region.")
    return result


def move_geometry(geom, old_xy, old_deg, new_xy, new_deg):
    # KiCad positive angles turn counter-clockwise on a screen with Y increasing down.
    g = affinity.rotate(geom, -(new_deg - old_deg), origin=old_xy)
    return affinity.translate(g, new_xy[0] - old_xy[0], new_xy[1] - old_xy[1])


def filled_outer(geom):
    if geom.geom_type == "Polygon":
        return Polygon(geom.exterior)
    if geom.geom_type == "MultiPolygon":
        return unary_union([Polygon(g.exterior) for g in geom.geoms])
    return geom


def encode(geom):
    return mapping(geom)


def decode(value):
    return shape(value)


def capsule(points, width):
    # Buffer approximates arcs inward; add chord tolerance in clearance checks.
    return LineString(points).buffer(width / 2, quad_segs=16)
