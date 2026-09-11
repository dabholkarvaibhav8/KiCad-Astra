"""Inspectable geometry metrics, without a misleading universal quality score."""

from shapely.geometry import LineString
from shapely.ops import unary_union

from kicad.geometry import decode
from kicad.validation import hpwl


def inspect_quality(state):
    findings = []
    silk = state.get("silkscreen", [])
    for fp in state["footprints"]:
        if abs((fp["rotation_deg"] + 45) % 90 - 45) > 1e-4:
            findings.append(f"{fp['reference']}: non-orthogonal orientation; confirm intent")
    for i, a in enumerate(silk):
        if a.get("height_mm", 1) < 1:
            findings.append(f"{a['reference']}: text below 1 mm; check readability")
        for b in silk[i + 1 :]:
            if a["side"] == b["side"] and decode(a["geometry"]).intersects(decode(b["geometry"])):
                findings.append(
                    f"Silkscreen bounds overlap: {a['reference'] or a['id']} / {b['reference'] or b['id']}"
                )
    return {
        "board_area_mm2": decode(state["outline"]).area if state.get("outline") else None,
        "projected_courtyard_union_mm2": unary_union(
            [decode(g) for f in state["footprints"] for g in f["courtyards"].values()]
        ).area,
        "estimated_net_span_mm": hpwl(state),
        "existing_trace_length_mm": sum(
            LineString(c["points_mm"]).length
            for c in state["copper"]
            if c["kind"] == "track" and len(c.get("points_mm", [])) > 1
        ),
        "findings": findings,
        "notes": [
            "Geometric metrics do not establish electrical quality or manufacturing readiness.",
            *state.get("silkscreen_errors", []),
        ],
    }
