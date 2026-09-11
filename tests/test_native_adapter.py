"""Exercise real kicad-python protobuf wrappers with a simulated IPC server."""

import tempfile
import unittest
from types import SimpleNamespace as NS

from kipy.board_types import (
    BoardLayer,
    BoardRectangle,
    Footprint3DModel,
    FootprintInstance,
    Net,
    Pad,
    PadType,
    Track,
    ViaType,
)
from kipy.geometry import PolygonWithHoles, PolyLineNode, Vector2
from kipy.proto.board import board_commands_pb2 as commands
from kipy.proto.common.types import DocumentSpecifier

from examples.demo_scene import connection, make_scene, uid
from kicad.board_reader import read_scene
from kicad.config import LayoutRules
from kicad.geometry import decode
from kicad.placement import stage_placements
from kicad.router import route_connection
from kicad.routing import stage_routes


def footprint():
    fp = FootprintInstance()
    fp.id.value = uid("real-fp")
    fp.layer = BoardLayer.BL_F_Cu
    fp.position = Vector2.from_xy_mm(5, 5)
    fp.reference_field.text.value = "U1"
    pad = Pad()
    pad.id.value = uid("real-pad")
    pad.number = "1"
    pad.position = Vector2.from_xy_mm(6, 5)
    pad.pad_type = PadType.PT_SMD
    pad.net = Net(name="SIGNAL")
    model = Footprint3DModel()
    model.filename = "test-model.step"
    model.visible = True
    fp.definition.items = [pad, model]
    return fp


def polygon(x, y):
    poly = PolygonWithHoles()
    for px, py in ((x - 0.4, y - 0.4), (x + 0.4, y - 0.4), (x + 0.4, y + 0.4), (x - 0.4, y + 0.4)):
        poly.outline.append(PolyLineNode.from_point(Vector2.from_xy_mm(px, py)))
    poly.outline.closed = True
    return poly.proto


class NativeAdapterTests(unittest.TestCase):
    def test_placement_rotates_real_pad_and_preserves_3d_metadata(self):
        fp = footprint()
        updated = []

        def update(items):
            # Force pack/unpack across the native protobuf boundary.
            updated.extend(FootprintInstance(i.proto) for i in items)
            return updated

        board = NS(get_footprints=lambda: [fp], update_items=update)
        count = stage_placements(
            board,
            [
                {
                    "reference": "U1",
                    "x_mm": 10,
                    "y_mm": 10,
                    "rotation_deg": 90,
                    "side": "front",
                    "reason": "test",
                }
            ],
        )
        self.assertEqual(count, 1)
        pad = updated[0].definition.pads[0]
        self.assertEqual(pad.position, Vector2.from_xy_mm(10, 9))
        self.assertAlmostEqual(pad.padstack.angle.degrees, 90)
        models = updated[0].definition.models
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].filename, "test-model.step")
        self.assertTrue(models[0].visible)

    def test_native_copper_has_stable_ids_nets_and_through_vias(self):
        route = route_connection(connection(), make_scene(), LayoutRules(), seed="native-test")
        route["segments"] = [
            {"layer": "F.Cu", "points_mm": [[5, 10], [10, 10]], "width_mm": 0.25},
            {"layer": "B.Cu", "points_mm": [[10, 10], [20, 10]], "width_mm": 0.25},
        ]
        route["vias"] = [{"position_mm": [10, 10], "diameter_mm": 0.65, "drill_mm": 0.3}]
        created = []

        def create(items):
            created.extend(type(i)(i.proto) for i in items)
            return created[-len(items) :]

        board = NS(
            get_nets=lambda: [Net(name="SIGNAL")],
            get_tracks=lambda: [],
            get_vias=lambda: [],
            create_items=create,
        )
        self.assertEqual(stage_routes(board, [route]), (2, 1))
        self.assertEqual([i.net.name for i in created], ["SIGNAL"] * 3)
        self.assertEqual(created[0].width, 250000)
        self.assertEqual(created[-1].type, ViaType.VT_THROUGH)
        self.assertEqual(created[-1].padstack.drill.start_layer, BoardLayer.BL_F_Cu)
        self.assertEqual(created[-1].padstack.drill.end_layer, BoardLayer.BL_B_Cu)
        ids = [i.id.value for i in created]
        stage_routes(board, [route])
        self.assertEqual([i.id.value for i in created[3:]], ids)

    def test_server_clamped_copper_is_rejected(self):
        route = route_connection(connection(), make_scene(), LayoutRules())

        def create(items):
            response = [Track(i.proto) for i in items]
            response[0].width = 100000
            return response

        board = NS(
            get_nets=lambda: [Net(name="SIGNAL")],
            get_tracks=lambda: [],
            get_vias=lambda: [],
            create_items=create,
        )
        with self.assertRaisesRegex(RuntimeError, "altered"):
            stage_routes(board, [route])

    def test_snapshot_maps_sparse_polygons_by_uuid_and_keeps_graphic_owner(self):
        fp = footprint()
        pad1 = fp.definition.pads[0]
        pad2 = Pad(pad1.proto)
        pad2.id.value = uid("second-pad")
        pad2.number = "2"
        pad2.position = Vector2.from_xy_mm(7, 5)
        fp.definition.items = [*fp.definition.items, pad2]
        graphic = BoardRectangle()
        graphic.id.value = uid("footprint-copper")
        graphic.layer = BoardLayer.BL_F_Cu
        graphic.top_left = Vector2.from_xy_mm(4, 4)
        graphic.bottom_right = Vector2.from_xy_mm(4.5, 4.5)
        fp.definition.items = [*fp.definition.items, graphic]
        fp.reference_field.text.id.value = uid("reference-text")
        fp.reference_field.layer = BoardLayer.BL_F_Cu
        edge = BoardRectangle()
        edge.id.value = uid("edge")
        edge.layer = BoardLayer.BL_Edge_Cuts
        edge.top_left = Vector2.from_xy_mm(0, 0)
        edge.bottom_right = Vector2.from_xy_mm(30, 20)

        def send(cmd, response_type):
            response = commands.PadShapeAsPolygonResponse()
            # Deliberately reverse order; omit the first pad on the back layer.
            response.pads.append(pad2.id)
            response.polygons.append(polygon(7, 5))
            if cmd.layer == BoardLayer.BL_F_Cu:
                response.pads.append(pad1.id)
                response.polygons.append(polygon(6, 5))
            return response

        with tempfile.TemporaryDirectory() as folder:
            doc = DocumentSpecifier()
            doc.project.path = folder
            doc.project.name = "example"
            board = NS(
                document=doc,
                name="example.kicad_pcb",
                client=NS(send=send),
                get_enabled_layers=lambda: [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu],
                get_footprints=lambda: [fp],
                get_pads=lambda: [pad1, pad2],
                get_tracks=lambda: [],
                get_vias=lambda: [],
                get_zones=lambda: [],
                get_shapes=lambda: [edge, graphic],
                get_text=lambda: [],
                get_dimensions=lambda: [],
                get_barcodes=lambda: [],
                get_groups=lambda: [],
                get_nets=lambda: [Net(name="SIGNAL")],
                get_netclass_for_nets=lambda _: {},
                get_item_bounding_box=lambda *a, **k: NS(
                    pos=Vector2.from_xy_mm(4, 4), size=Vector2.from_xy_mm(4, 4)
                ),
            )
            scene = read_scene(board, NS(get_version=lambda: "10.0.6"))
        self.assertEqual(scene["geometry_errors"], [])
        by_id = {p["id"]: p for p in scene["pads"]}
        self.assertAlmostEqual(decode(by_id[pad1.id.value]["layers"]["F.Cu"]).centroid.x, 6)
        self.assertNotIn("B.Cu", by_id[pad1.id.value]["layers"])
        self.assertAlmostEqual(decode(by_id[pad2.id.value]["layers"]["B.Cu"]).centroid.x, 7)
        graphic_rows = [c for c in scene["copper"] if c["id"] == graphic.id.value]
        self.assertEqual(len(graphic_rows), 1)
        self.assertEqual(graphic_rows[0]["owner"], "U1")
        self.assertEqual(
            next(c for c in scene["copper"] if c["id"] == uid("reference-text"))["owner"], "U1"
        )
