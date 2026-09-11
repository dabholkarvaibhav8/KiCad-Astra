"""Run with KiCad's pcbnew-enabled Python; create disposable CLI test boards."""

import argparse
import json
import shutil
from pathlib import Path


def main():
    import pcbnew

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--routes", type=Path, help="Compiled route JSON exported by the local engine"
    )
    parser.add_argument("--labels", type=Path, help="Local reference-label operations")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    board = pcbnew.BOARD()
    nets = {}
    for name in ("SIGNAL", "GND"):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net
    for ref, x, y, net in [("U1", 5, 10, "SIGNAL"), ("R1", 25, 10, "SIGNAL"), ("J1", 5, 4, "GND")]:
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetAttributes(pcbnew.FP_SMD)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        pad = pcbnew.PAD(fp)
        pad.SetNumber("1")
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1), pcbnew.FromMM(1)))
        pad_layers = pcbnew.LSET()
        for layer in (pcbnew.F_Cu, pcbnew.F_Paste, pcbnew.F_Mask):
            pad_layers.AddLayer(layer)
        pad.SetLayerSet(pad_layers)
        pad.SetPosition(fp.GetPosition())
        pad.SetNet(nets[net])
        fp.Add(pad)
        courtyard = pcbnew.PCB_SHAPE(fp)
        courtyard.SetShape(pcbnew.SHAPE_T_RECT)
        courtyard.SetLayer(pcbnew.F_CrtYd)
        courtyard.SetWidth(pcbnew.FromMM(0.05))
        courtyard.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x - 1), pcbnew.FromMM(y - 1)))
        courtyard.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x + 1), pcbnew.FromMM(y + 1)))
        fp.Add(courtyard)
        board.Add(fp)
    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetLayer(pcbnew.Edge_Cuts)
    edge.SetWidth(pcbnew.FromMM(0.05))
    edge.SetStart(pcbnew.VECTOR2I(0, 0))
    edge.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(30), pcbnew.FromMM(20)))
    board.Add(edge)
    board.SetFileName(str(args.output / "kicad-astra-native-fixture.kicad_pcb"))
    pcbnew.SaveBoard(board.GetFileName(), board)
    (args.output / "kicad-astra-native-fixture.kicad_pro").write_text(
        json.dumps(
            {
                "meta": {"version": 1},
                "net_settings": {
                    "classes": [
                        {
                            "name": "Default",
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.65,
                            "via_drill": 0.3,
                        }
                    ]
                },
            }
        )
    )

    def track(a, b, net, width):
        item = pcbnew.PCB_TRACK(board)
        item.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
        item.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
        item.SetLayer(pcbnew.F_Cu)
        item.SetWidth(pcbnew.FromMM(width))
        item.SetNet(nets[net])
        board.Add(item)

    routes = json.loads(args.routes.read_text()) if args.routes else []
    for route in routes:
        if route["vias"] or any(s["layer"] != "F.Cu" for s in route["segments"]):
            raise ValueError("This simple native fixture expects front-layer traces without vias")
        for segment in route["segments"]:
            for a, b in zip(segment["points_mm"], segment["points_mm"][1:]):
                track(a, b, route["net"], segment["width_mm"])
    if args.labels:
        by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
        for op in json.loads(args.labels.read_text()):
            text = by_ref[op["reference"]].Reference()
            text.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(op["x_mm"]), pcbnew.FromMM(op["y_mm"])))
            text.SetTextSize(
                pcbnew.VECTOR2I(pcbnew.FromMM(op["height_mm"]), pcbnew.FromMM(op["height_mm"]))
            )
            text.SetTextThickness(pcbnew.FromMM(op["stroke_mm"]))
            text.SetTextAngle(pcbnew.EDA_ANGLE(0, pcbnew.DEGREES_T))
            text.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
            text.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
            text.SetVisible(True)
    if routes:
        pcbnew.SaveBoard(str(args.output / "candidate.kicad_pcb"), board)
        # Anchor the negative control to the GND pad. KiCad can reassign the net
        # of a floating track to the SIGNAL copper it touches on board load.
        track((5, 4), (10, 4), "GND", 0.25)
        track((10, 4), (10, 12), "GND", 0.25)
        pcbnew.SaveBoard(str(args.output / "shorted.kicad_pcb"), board)
        for name in ("candidate", "shorted"):
            shutil.copy2(
                args.output / "kicad-astra-native-fixture.kicad_pro",
                args.output / (name + ".kicad_pro"),
            )
    print("Native fixture generated with KiCad", pcbnew.GetBuildVersion())


if __name__ == "__main__":
    main()
