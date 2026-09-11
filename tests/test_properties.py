"""Geometric invariants tested across generated layouts and transforms."""

from hypothesis import given, settings
from hypothesis import strategies as st
from shapely.geometry import LineString, Point, box

from examples.demo_scene import connection, make_scene
from kicad.config import LayoutRules
from kicad.geometry import encode, move_geometry
from kicad.router import route_connection


@settings(max_examples=24, deadline=None, derandomize=True)
@given(left=st.integers(10, 13), right=st.integers(16, 19), half_height=st.integers(1, 4))
def test_routed_path_keeps_analytical_obstacle_clearance(left, right, half_height):
    state = make_scene()
    obstacle = box(left, 10 - half_height, right, 10 + half_height)
    state["copper"].append(
        {
            "id": "test-obstacle",
            "owner": "",
            "kind": "graphic",
            "net": "GND",
            "layer": "F.Cu",
            "geometry": encode(obstacle),
        }
    )
    route = route_connection(connection(), state, LayoutRules(grid_mm=0.5, route_timeout_s=5))
    path = LineString(route["segments"][0]["points_mm"])
    assert path.distance(obstacle) >= 0.2 + 0.25 / 2
    assert path.coords[0] == (5, 10) and path.coords[-1] == (25, 10)
    assert box(0.3, 0.3, 29.7, 19.7).covers(path.buffer(0.125))


@settings(max_examples=50, deadline=None, derandomize=True)
@given(
    x=st.floats(-50, 50, allow_nan=False),
    y=st.floats(-50, 50, allow_nan=False),
    angle=st.integers(-720, 720),
)
def test_rigid_transform_round_trip_preserves_geometry(x, y, angle):
    point = Point(2, 3)
    moved = move_geometry(point, (0, 0), 0, (x, y), angle)
    restored = move_geometry(moved, (x, y), angle, (0, 0), 0)
    assert restored.distance(point) < 1e-10
