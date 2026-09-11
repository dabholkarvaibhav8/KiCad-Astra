# KiCad Astra roadmap

This document separates shipped code from planned engineering work.

## Implemented in 1.0.0

- Strict hosted-model planning, bounded repair, UUID-based connection intent.
- Deterministic geometry checks, bounded local A* routing and native DRC diff.
- Transaction staging, stale-state rejection, backup, rollback and audit data.
- Reference-label proposals with same-side obstacles, readability dimensions,
  locked/hidden preservation and native checks before application.
- Measured layout report and isolated native fabrication preflight/export.
- Installer, diagnostics, offline example, property/boundary/native CLI tests,
  release archive, developer docs and GitHub CI configuration.

Actual verification status is in [VALIDATION.md](VALIDATION.md).

## Release acceptance still required

1. Execute the live editor preview/rollback test and manual Apply/Undo checks
   on Windows, macOS and Linux with the supported KiCad release.
2. Run the opt-in live API check with an account that has model access.
3. Validate real engineer-owned boards with schematic parity, custom rules,
   zones, holes, backside assembly and the selected fabricator's limits.
4. Observe the GitHub CI matrix running on the uploaded repository.

## Planned, not implemented

- Differential-pair routing, skew/length tuning and impedance-aware routing.
- KiCad interactive push-and-shove integration and measured large-board scaling.
- Electrical/thermal simulation, current-capacity and return-path verification.
- Semantic connector pinout, polarity and product-label authoring with verified
  circuit meaning; reference cleanup currently never invents these labels.
- Vendor-specific DFM adapters, verified BOM/MPN/variant generation, panelization,
  castellation review, blind/buried via workflows and automated assembly approval.
- Offline local-model backends and a broader compatibility matrix.

Prioritize by reproducible user boards and measurable outcomes: successful
setup, DRC regressions caught, completed reviewed connections and fewer manual
label corrections. No automatic fabrication certification is promised.
