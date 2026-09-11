"""Reproducible offline scene for previewing and testing the local engine."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from shapely.geometry import Point, box

from agent.tools import empty_plan
from kicad.board_reader import BoardSnapshot, digest
from kicad.geometry import encode


def uid(name):
    return str(uuid5(NAMESPACE_URL, "kicad-astra-demo:" + name))


def make_scene():
    pads = []
    footprints = []
    copper = []
    for ref, pos, value in [
        ("U1", (5, 10), "Controller"),
        ("R1", (25, 10), "1k"),
        ("J1", (5, 4), "Connector"),
    ]:
        footprints.append(
            {
                "id": uid(ref),
                "reference": ref,
                "value": value,
                "position_mm": pos,
                "rotation_deg": 0,
                "side": "front",
                "locked": ref == "J1",
                "grouped": False,
                "courtyards": {
                    "front": encode(box(pos[0] - 1, pos[1] - 1, pos[0] + 1, pos[1] + 1))
                },
                "conservative_body": False,
                "unsupported_children": [],
            }
        )
        net = "SIGNAL" if ref != "J1" else "GND"
        g = encode(Point(pos).buffer(0.5))
        pads.append(
            {
                "id": uid(ref + ".1"),
                "reference": ref,
                "number": "1",
                "label": ref + ".1",
                "net": net,
                "position_mm": pos,
                "layers": {"F.Cu": g},
                "type": "PT_SMD",
            }
        )
        copper.append(
            {
                "id": uid(ref + ".1"),
                "kind": "pad",
                "owner": ref,
                "net": net,
                "layer": "F.Cu",
                "geometry": g,
            }
        )
    return {
        "format_version": 2,
        "units": "mm",
        "board_file": "synthetic-demo.kicad_pcb",
        "kicad_version": "Synthetic demo — no KiCad connection",
        "curve_tolerance_mm": 0.005,
        "outline": encode(box(0, 0, 30, 20)),
        "copper_layers": ["F.Cu", "B.Cu"],
        "footprints": footprints,
        "pads": pads,
        "nets": [
            {"name": "SIGNAL", "clearance_mm": 0.2, "track_width_mm": 0.25},
            {"name": "GND", "clearance_mm": 0.2},
        ],
        "copper": copper,
        "silkscreen": [
            {
                "id": uid(fp["reference"] + ".ref"),
                "kind": "reference",
                "reference": fp["reference"],
                "side": "front",
                "locked": fp["locked"],
                "text": fp["reference"],
                "position_mm": fp["position_mm"],
                "height_mm": 0.8,
                "stroke_mm": 0.15,
                "geometry": encode(
                    box(
                        fp["position_mm"][0] - 1,
                        fp["position_mm"][1] - 0.5,
                        fp["position_mm"][0] + 1,
                        fp["position_mm"][1] + 0.5,
                    )
                ),
            }
            for fp in footprints
        ],
        "silkscreen_errors": [],
        "holes": [],
        "keepouts": [],
        "project_rules": {},
        "geometry_errors": [],
        "warnings": ["Synthetic geometry for software testing; this is not a functional circuit."],
        "counts": {
            "footprints": 3,
            "pads": 3,
            "nets": 2,
            "track_segments": 0,
            "vias": 0,
            "zones": 0,
        },
    }


def connection():
    return {
        "net": "SIGNAL",
        "from_pad_id": uid("U1.1"),
        "to_pad_id": uid("R1.1"),
        "layers": ["F.Cu", "B.Cu"],
        "reason": "Synthetic pad-to-pad routing demonstration.",
    }


def demo_proposal():
    plan = empty_plan("Synthetic routing demonstration")
    plan["connections"] = [connection()]
    return plan


class DemoSession:
    demo = True

    def __init__(self):
        self.lock = threading.RLock()
        self.state = make_scene()
        self.state["copper"].append(
            {
                "id": uid("obstacle"),
                "kind": "graphic",
                "owner": "",
                "net": "GND",
                "layer": "F.Cu",
                "geometry": encode(box(14, 4, 16, 16)),
            }
        )
        self.board_path = Path("synthetic-demo.kicad_pcb")

    def capture(self):
        data = copy.deepcopy(self.state)
        return BoardSnapshot(data, "synthetic", digest(data), self.board_path)

    def assert_current(self, fingerprint):
        if fingerprint != digest(self.state):
            raise RuntimeError("Demo snapshot changed.")
