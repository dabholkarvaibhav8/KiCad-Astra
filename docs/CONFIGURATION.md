# KiCad Astra configuration

Run commands from the repository root. UI constraints are JSON objects;
[constraints.example.json](../constraints.example.json) contains current defaults.

## Constraint reference

All dimensional values are millimetres. Partial JSON inherits defaults.
`constraints.example.json` contains the full default configuration.

| Field | Default | Effect |
| --- | --- | --- |
| `clearance_mm` | 0.20 | Local copper clearance floor |
| `track_width_mm` | 0.25 | Routing width floor |
| `edge_clearance_mm` | 0.30 | Copper/placement edge margin as checked locally |
| `courtyard_clearance_mm` | 0.10 | Placement courtyard separation |
| `via_diameter_mm` | 0.65 | Via diameter floor |
| `via_drill_mm` | 0.30 | Via drill floor |
| `annular_ring_mm` | 0.15 | Minimum requested annular ring |
| `hole_clearance_mm` | 0.25 | Hole clearance fallback |
| `grid_mm` | 0.25 | Search spacing; minimum 0.025 |
| `max_move_mm` | 25 | Maximum footprint translation |
| `via_cost_mm` | 8 | Equivalent distance cost per transition |
| `max_search_nodes` | 150000 | Expansion budget; accepted range 100–1000000 |
| `route_timeout_s` | 15 | Search time budget per connection |
| `max_connections` | 32 | Per-plan connection limit; accepted range 0–100 |
| `max_revisions` | 2 | Repair attempts after the first request; range 0–5 |
| `allow_vias` | false | Enable through-via transitions |
| `allowed_layers` | F.Cu, B.Cu | Permitted planar layers, also checked against the board |
| `fixed_references` | empty | Specific references preserved |
| `fixed_prefixes` | J, H, MH | Reference prefixes preserved |
| `manual_nets` | empty | Net names the router must reject |
| `placement_regions` | empty | Reference → polygon containing proposed courtyard |
| `proximity` | empty | Named pad-pair maximum distance rules |

Dimensions and timeouts must be positive finite numbers, not booleans. Via
diameter must satisfy drill plus twice the requested annular ring. Polygons
must contain at least three finite 2D points and be valid with nonzero area.
The effective routing dimensions may exceed these defaults to satisfy captured
net-class and supported project minima.

```json
{
  "fixed_references": ["J1", "SW1"],
  "manual_nets": ["USB_D+", "USB_D-", "RF_FEED"],
  "allow_vias": false,
  "placement_regions": {
    "U1": [[10, 10], [30, 10], [30, 25], [10, 25]]
  },
  "proximity": [
    {"a": "U1.3", "b": "C1.1", "max_mm": 2.0}
  ]
}
```

Replace labels and dimensions with your board's requirements. Pad proximity
measures geometry; it does not establish electrical decoupling effectiveness.

For text finishing use [labels.example.json](../labels.example.json); for fabrication use [manufacturing.example.json](../manufacturing.example.json). Their field mappings and limits are in [Finishing and fabrication](FINISHING_AND_FABRICATION.md).
