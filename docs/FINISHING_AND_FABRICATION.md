# KiCad Astra finishing and fabrication

Complete label and fabrication contracts for 1.0.0. Commands assume
the repository root; return to [the README](../README.md) for initial setup.

## Reference labels and layout quality

After reviewing and applying placement and routing, save the board and capture
it again. Select **Arrange reference labels**. Choose `labels.example.json`,
or cancel the file chooser to use the same defaults. Review the white proposed
label boxes in **Board preview** and the exact positions in **Proposed changes**.
Run **Test with KiCad DRC**, inspect its result, then **Apply checked plan**.
Save in KiCad and recapture. This operation needs no API key or network request.

Only visible, unlocked reference fields on `F.SilkS` or `B.SilkS` are moved.
Locked footprint owners, locked fields, hidden references, value fields,
product text and other artwork stay as captured. Reference cleanup does not
invent connector pinouts, polarity, ratings or names such as Charging/Done;
those require verified circuit meaning and manual product-label design.

| Label setting | Default | Meaning |
| --- | ---: | --- |
| `height_mm` | 1.0 | Text height and width in the native stroke font |
| `stroke_mm` | 0.15 | Stroke thickness, at most one quarter of height |
| `clearance_mm` | 0.2 | Gap to fixed text, courtyard and hole bounds |
| `mask_margin_mm` | 0.15 | Additional conservative pad/via mask allowance |
| `edge_margin_mm` | 0.3 | Label-box inset from the board outline |
| `grid_mm` | 0.25 | Placement grid; supported minimum 0.025 mm |
| `max_offset_mm` | 5.0 | Maximum candidate-box distance from the owner courtyard |

The engine enumerates top/bottom/left/right positions on five spacing rings,
snaps candidates to the configured grid, and tests whole boxes against
same-side obstacles and the inward-buffered outline. Reference order is stable,
so the same snapshot and style produce the same operations. A failed position
is reported and blocks application of the bundle. This bounded search can fail
on dense boards even when a human could find a better global arrangement.

`capture_silkscreen()` requests native item bounding boxes. Proposed glyph
boxes deliberately overestimate typical stroke text. Native mask expansion,
fonts, artwork and custom rules still require the native DRC result and visual
inspection. The native adapter centers text, removes bold/italic styling,
uses zero text angle with keep-upright, and mirrors backside references. It
checks every returned owner UUID, reference identity, component pose, text
position and style; partial or clamped updates fail the transaction.

**Layout quality** reports board area, projected courtyard-union area,
estimated net span, existing trace length and readability/overlap observations.
Projected area combines both board sides. Net span is a geometric estimate,
not routed length or signal integrity. These measured quantities are not a
universal placement-quality score.

Label operations are included in the session report and approval hash.
Exported label sessions are reports only: import refuses them and asks for
local regeneration from a fresh capture. Placement and routing proposals
continue to use strict model schema v2. The label stage has no model output.

## Fabrication preparation

**Prepare fabrication…** runs a stricter gate than incremental layout review:
it requires zero reported native DRC items, including warnings and exclusions.
It also reenables every check reported as ignored on the isolated project
copy and reruns DRC. An unknown or still-disabled check blocks export. The
original project keeps its settings; the report lists reenabled checks.

1. Complete the schematic/PCB update, engineer review and KiCad saves. Save
   `.kicad_pro`, `.kicad_pcb`, custom rules and all hierarchy sheets.
2. Copy `manufacturing.example.json` and replace its generic limits with the
   limits you have confirmed for the intended stackup and fabrication process.
   The example is not a named vendor capability profile.
3. Capture the saved board. Select **Prepare fabrication…**, choose the profile,
   then choose an output parent directory. A new timestamped folder is created.
4. Inspect **Fabrication** and `manufacturing-report.json`. A blocked report
   retains native findings and copied inputs, without a fabrication ZIP.
5. For an exported result, inspect Gerber layers, outlines, drill plots,
   registration, bottom-side placement conventions and all product labels.
   Complete electrical, mechanical and fabricator review before ordering.

A headless interface is also available, with your environment's Python:

```powershell
.\.venv\Scripts\python.exe -m kicad.manufacturing --board "C:\PCB\project.kicad_pcb" --profile manufacturing.example.json --output "C:\PCB\review-output-001" --cli "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
```

On Linux/macOS use `.venv/bin/python` and your installed CLI path. The module
also accepts `KICAD_ASTRA_KICAD_CLI`, then searches PATH. The GUI resolves the
CLI from the active KiCad installation. The output directory must not exist.
Exit status 0 means the configured fabrication checks passed; status 1 means
blocked/failed. Consult the report before treating any output as reviewed.

### Fabrication profile contract

| Field | Example | Enforcement |
| --- | --- | --- |
| `name` | Generic review profile | Descriptive name, recorded in report |
| `copper_layers` | `["F.Cu", "B.Cu"]` | Exact ordered match with the native board layer table |
| `board_thickness_mm` | 1.6 | Native statistics match within 0.01 mm |
| `min_clearance_mm` | 0.2 | KiCad `rules.min_clearance` |
| `min_track_width_mm` | 0.25 | KiCad `rules.min_track_width` |
| `min_drill_mm` | 0.3 | KiCad `rules.min_through_hole_diameter` |
| `min_annular_ring_mm` | 0.15 | KiCad `rules.min_via_annular_width` |
| `min_edge_clearance_mm` | 0.3 | KiCad `rules.min_copper_edge_clearance` |
| `min_silk_height_mm` | 1.0 | KiCad `rules.min_text_height` |
| `min_silk_stroke_mm` | 0.15 | KiCad `rules.min_text_thickness` |
| `min_silk_clearance_mm` | 0.2 | KiCad `rules.min_silk_clearance` |
| `require_schematic_parity` | true | Require a matching root schematic and run native parity checks |

Numbers must be positive, finite and within KiCad's supported setting ranges.
Unknown fields and malformed stacks are rejected. A four-layer board needs
`["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]` in its actual order. The profile does not
change the board's layer stack, copper weights, dielectric materials or
impedance targets. Confirm those directly with the manufacturer. Annular-ring
and drill floors cover KiCad's mapped constraints; they do not certify every
possible pad, slot, microvia or castellation process.

The code snapshots at most 500 files / 100 MB, retains hierarchy paths,
requires matching native board/project names, and rejects linked input files.
It copies the PCB, project, optional custom rules and (when parity is enabled)
schematic files under the project directory. Hierarchy sheets and dependencies
outside that tree need a self-contained saved project. Missing dependencies
must be resolved before export. Source hashes are checked during copying and
again before committing the output directory. Input files are never rewritten.

Each configured native minimum becomes `max(saved minimum, profile minimum)`
in the copied project. Native DRC refills zones and saves only the copied board.
The narrow layer-table reader rejects syntax it does not support. Native
statistics must confirm an outline and thickness; no empty, unverified result
is accepted as a fabrication pass.

The subprocess runner uses argument arrays, bounded timeouts, cancellation,
termination and reaping. Exports are written to a private temporary directory;
failed jobs remove partial outputs. Successful or DRC-blocked reports are
committed to the selected new folder. Existing output folders are never
replaced. A report and a set of plot files are not an electronic-signoff system.

### Output contract

| Output | Content |
| --- | --- |
| `manufacturing-report.json` | Profile, result, native DRC, statistics, source/refilled hashes and remaining review notes |
| `source/` | Copied design inputs, strengthened rules, zone-refilled board and native DRC evidence |
| `board-statistics.json` | Native KiCad board statistics |
| `fabrication/*.gbr` | Gerber X2: every copper layer, front/back mask, front/back silk and Edge.Cuts |
| `fabrication/*.drl` | Excellon drill output when required by the board |
| `fabrication/placement.csv` | Placement reference data on both sides, excluding DNP items |
| `fabrication/*.svg` | Separate F.Fab, B.Fab and Edge.Cuts layer drawings |
| `fabrication/SHA256SUMS.json` | File-content integrity manifest |
| `kicad-astra-fabrication.zip` | Generated fabrication/reference files after the configured checks pass |

The exporter uses the absolute board origin, millimetre drill/placement data,
and separate plated/nonplated drill output. Assembly SVG files are separate
layer references, not a composed verified assembly drawing. Solder-paste
stencils, a checked BOM with MPNs, variants, purchasing data, controlled
impedance, panelization and vendor approval are not produced. Accordingly,
`assembly_ready` remains false. `fabrication_checks_passed` identifies a
completed software gate; `status="exported_for_review"` states the next step.
The synthetic fixture alone is insufficient to validate your production PCB.

Native command behavior is documented in the
[KiCad 10 CLI manual](https://docs.kicad.org/10.0/en/cli/cli.html).
Project-rule names are mapped to KiCad's
[board design settings implementation](https://github.com/KiCad/kicad-source-mirror/blob/10.0/pcbnew/board_design_settings.cpp).
