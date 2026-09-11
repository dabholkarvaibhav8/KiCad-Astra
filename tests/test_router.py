import unittest

from shapely.geometry import LineString, box

from agent.workflow import evaluate
from examples.demo_scene import DemoSession, connection, demo_proposal, make_scene
from kicad.config import LayoutRules
from kicad.geometry import encode
from kicad.router import RoutingError, RoutingSpace, route_connection
from kicad.validation import validate_plan


def wall(state, layers=("F.Cu",), full=False):
    for layer in layers:
        state["copper"].append(
            {
                "id": "obstacle-" + layer,
                "kind": "graphic",
                "owner": "",
                "net": "GND",
                "layer": layer,
                "geometry": encode(box(14, -1 if full else 4, 16, 21 if full else 16)),
            }
        )


class RouterTests(unittest.TestCase):
    def test_direct_connection_has_exact_endpoints(self):
        route = route_connection(connection(), make_scene(), LayoutRules(), seed="fixed")
        self.assertEqual(route["segments"][0]["points_mm"], [[5, 10], [25, 10]])
        self.assertTrue(validate_plan(demo_proposal(), make_scene(), routes=[route]).ok)

    def test_obstacle_detour_meets_clearance(self):
        s = make_scene()
        wall(s)
        route = route_connection(connection(), s, LayoutRules(grid_mm=0.5))
        path = LineString(route["segments"][0]["points_mm"])
        self.assertGreater(path.length, 20)
        self.assertGreaterEqual(path.distance(box(14, 4, 16, 16)), 0.2 + 0.125)
        self.assertTrue(validate_plan(demo_proposal(), s, LayoutRules(grid_mm=0.5), [route]).ok)

    def test_hidden_layer_copper_blocks_through_vias(self):
        s = make_scene()
        s["copper_layers"].append("In1.Cu")
        s["copper"].append(
            {
                "id": "inner",
                "kind": "zone",
                "owner": "",
                "net": "GND",
                "layer": "In1.Cu",
                "geometry": encode(box(0, 0, 30, 20)),
            }
        )
        r = LayoutRules(allow_vias=True)
        space = RoutingSpace(s, r, "SIGNAL", 0.25, 0.65, 0.3, ["F.Cu", "B.Cu"])
        self.assertFalse(space.via_free((10, 10)))

    def test_layer_transition_uses_real_vias(self):
        s = make_scene()
        wall(s, full=True)
        rules = LayoutRules(allow_vias=True, grid_mm=1, via_cost_mm=1, route_timeout_s=5)
        route = route_connection(connection(), s, rules)
        self.assertGreaterEqual(len(route["vias"]), 2)
        self.assertIn("B.Cu", [seg["layer"] for seg in route["segments"]])
        report = validate_plan(demo_proposal(), s, rules, [route])
        self.assertTrue(report.ok, report.as_text())

    def test_unroutable_path_fails_with_limits(self):
        s = make_scene()
        wall(s, full=True)
        with self.assertRaises(RoutingError):
            route_connection(
                connection(), s, LayoutRules(grid_mm=1, max_search_nodes=1000, route_timeout_s=1)
            )

    def test_diagonal_cannot_cut_obstacle_corner(self):
        s = make_scene()
        s["copper"].append(
            {
                "id": "corner",
                "kind": "graphic",
                "owner": "",
                "net": "GND",
                "layer": "F.Cu",
                "geometry": encode(box(9, 9, 10, 10)),
            }
        )
        space = RoutingSpace(s, LayoutRules(), "SIGNAL", 0.25, 0.65, 0.3, ["F.Cu"])
        self.assertFalse(space.segment_free((8, 10), (10, 8), "F.Cu"))

    def test_effective_net_class_sets_width(self):
        s = make_scene()
        s["nets"][0]["track_width_mm"] = 0.6
        r = route_connection(connection(), s, LayoutRules())
        self.assertEqual(r["segments"][0]["width_mm"], 0.6)

    def test_unknown_and_wrong_net_endpoints(self):
        for change in ({"net": "GND"}, {"from_pad_id": "invented"}):
            c = {**connection(), **change}
            with self.assertRaises(RoutingError):
                route_connection(c, make_scene(), LayoutRules())

    def test_rejects_disconnected_or_shorting_path(self):
        s = make_scene()
        wall(s)
        r = route_connection(connection(), s, LayoutRules(grid_mm=1))
        r["segments"][0]["points_mm"] = [[5, 10], [25, 10]]
        self.assertFalse(validate_plan(demo_proposal(), s, routes=[r]).ok)
        r["segments"][0]["points_mm"] = [[8, 10], [25, 10]]
        self.assertTrue(
            any("endpoint" in e for e in validate_plan(demo_proposal(), s, routes=[r]).errors)
        )

    def test_stable_route_identifiers(self):
        a = route_connection(connection(), make_scene(), LayoutRules(), seed="one")
        b = route_connection(connection(), make_scene(), LayoutRules(), seed="one")
        self.assertEqual(a, b)

    def test_complete_offline_pipeline(self):
        s = DemoSession().capture()
        bundle = evaluate(demo_proposal(), s, LayoutRules(grid_mm=1), "routing")
        self.assertTrue(bundle.report.ok, bundle.report.as_text())
        before = bundle.content_hash()
        bundle.rules.clearance_mm = 0.3
        self.assertNotEqual(before, bundle.content_hash())

    def test_direct_route_obeys_layer_order_for_multilayer_pads(self):
        s = make_scene()
        for pad in s["pads"]:
            pad["layers"]["B.Cu"] = pad["layers"]["F.Cu"]
        c = connection()
        c["layers"] = ["B.Cu", "F.Cu"]
        route = route_connection(c, s, LayoutRules())
        self.assertEqual(route["segments"][0]["layer"], "B.Cu")
