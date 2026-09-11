import unittest

from shapely.geometry import LineString, Point, box

from agent.tools import empty_plan
from examples.demo_scene import make_scene
from kicad.config import LayoutRules
from kicad.geometry import arc_points, closed_region, encode
from kicad.validation import projected_scene, validate_plan


def move(ref="U1", x=8, y=10, angle=0, side="front"):
    p = empty_plan()
    p["placements"] = [
        {
            "reference": ref,
            "x_mm": x,
            "y_mm": y,
            "rotation_deg": angle,
            "side": side,
            "reason": "Test",
        }
    ]
    return p


class GeometryValidationTests(unittest.TestCase):
    def test_accepts_clear_placement(self):
        self.assertTrue(validate_plan(move(), make_scene()).ok)

    def test_locked_and_fixed_parts(self):
        self.assertFalse(validate_plan(move("J1", 8, 4), make_scene()).ok)
        self.assertFalse(
            validate_plan(move(), make_scene(), LayoutRules(fixed_references=["U1"])).ok
        )

    def test_rejects_extent_outside_board_even_if_origin_inside(self):
        result = validate_plan(move(x=0.7), make_scene())
        self.assertTrue(any("boundary" in e for e in result.errors))

    def test_cutout_is_not_board_area(self):
        s = make_scene()
        s["outline"] = encode(box(0, 0, 30, 20).difference(box(7, 8, 9, 12)))
        self.assertFalse(validate_plan(move(x=8), s).ok)

    def test_same_side_courtyard_collision(self):
        self.assertFalse(validate_plan(move(x=24), make_scene()).ok)

    def test_opposite_side_courtyard_is_independent(self):
        s = make_scene()
        s["footprints"][1]["side"] = "back"
        s["footprints"][1]["courtyards"] = {"back": s["footprints"][1]["courtyards"]["front"]}
        for p in s["pads"]:
            if p["reference"] == "R1":
                p["layers"] = {"B.Cu": p["layers"]["F.Cu"]}
        for c in s["copper"]:
            if c["owner"] == "R1":
                c["layer"] = "B.Cu"
        self.assertTrue(validate_plan(move(x=25), s).ok)

    def test_attached_copper_blocks_movement(self):
        s = make_scene()
        s["copper"].append(
            {
                "id": "track",
                "kind": "track",
                "owner": "",
                "net": "SIGNAL",
                "layer": "F.Cu",
                "geometry": encode(LineString([(5, 10), (8, 10)]).buffer(0.125)),
            }
        )
        self.assertTrue(any("attached" in e for e in validate_plan(move(), s).errors))

    def test_pad_keepout(self):
        s = make_scene()
        s["keepouts"] = [
            {
                "id": "keep",
                "layers": ["F.Cu"],
                "geometry": encode(box(7, 9, 9, 11)),
                "pads": True,
                "footprints": False,
                "tracks": False,
                "vias": False,
            }
        ]
        self.assertFalse(validate_plan(move(), s).ok)

    def test_explicit_region_and_proximity(self):
        rules = LayoutRules(placement_regions={"U1": [[1, 1], [7, 1], [7, 14], [1, 14]]})
        self.assertFalse(validate_plan(move(), make_scene(), rules).ok)
        rules = LayoutRules(proximity=[{"a": "U1.1", "b": "R1.1", "max_mm": 2}])
        self.assertTrue(
            any("exceeds" in e for e in validate_plan(move(), make_scene(), rules).errors)
        )

    def test_projection_rotates_pads_in_kicad_direction(self):
        s = make_scene()
        s["pads"][0]["position_mm"] = (6, 10)
        moved = projected_scene(s, move(x=8, y=10, angle=90)["placements"])
        self.assertAlmostEqual(moved["pads"][0]["position_mm"][0], 8)
        self.assertAlmostEqual(moved["pads"][0]["position_mm"][1], 9)
        self.assertEqual(s["pads"][0]["position_mm"], (6, 10))

    def test_geometry_failure_blocks_actions_but_allows_review(self):
        s = make_scene()
        s["geometry_errors"] = ["Missing pad shape"]
        self.assertFalse(validate_plan(move(), s).ok)
        self.assertTrue(validate_plan(empty_plan(), s).ok)

    def test_outline_even_odd_with_cutout(self):
        outer = box(0, 0, 30, 20).exterior
        hole = box(7, 8, 9, 12).exterior
        g = closed_region([outer, hole])
        self.assertAlmostEqual(g.area, 592)
        self.assertFalse(g.covers(Point(8, 10)))

    def test_open_outline_rejected(self):
        with self.assertRaises(ValueError):
            closed_region([LineString([(0, 0), (10, 0), (10, 10)])])

    def test_arc_goes_through_correct_half_circle(self):
        points = arc_points((1, 0), (0, 1), (-1, 0))
        self.assertGreater(max(y for x, y in points), 0.99)
        self.assertGreaterEqual(min(y for x, y in points), -1e-9)

    def test_constraints_reject_invalid_numeric_types(self):
        for data in (
            {"clearance_mm": False},
            {"grid_mm": float("nan")},
            {"max_revisions": True},
            {"unknown": 1},
        ):
            with self.assertRaises(ValueError):
                LayoutRules.from_dict(data)

    def test_moved_copper_respects_unplated_hole_clearance(self):
        s = make_scene()
        s["holes"].append(
            {"id": "unplated", "owner": "", "net": "", "geometry": encode(Point(8, 10).buffer(0.3))}
        )
        self.assertTrue(any("drill hole" in e for e in validate_plan(move(), s).errors))

    def test_moved_drill_cannot_cross_other_holes(self):
        s = make_scene()
        s["holes"].extend(
            [
                {
                    "id": s["pads"][0]["id"],
                    "owner": "U1",
                    "net": "SIGNAL",
                    "geometry": encode(Point(5, 10).buffer(0.2)),
                },
                {
                    "id": "fixed-drill",
                    "owner": "",
                    "net": "SIGNAL",
                    "geometry": encode(Point(8.4, 10).buffer(0.2)),
                },
            ]
        )
        self.assertTrue(any("conflicts with hole" in e for e in validate_plan(move(), s).errors))

    def test_moved_graphic_is_transformed_and_checked_for_shorts(self):
        s = make_scene()
        s["copper"].append(
            {
                "id": "graphic",
                "kind": "graphic",
                "owner": "U1",
                "net": "",
                "layer": "F.Cu",
                "geometry": encode(box(9, 9, 10, 11)),
            }
        )
        s["copper"].append(
            {
                "id": "obstacle",
                "kind": "graphic",
                "owner": "",
                "net": "GND",
                "layer": "F.Cu",
                "geometry": encode(box(12, 9, 13, 11)),
            }
        )
        report = validate_plan(move(), s)
        self.assertTrue(any("graphic" in e for e in report.errors))
