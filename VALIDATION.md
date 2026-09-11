# KiCad Astra verification record

**Version: 1.0.0.** This is an installable source release with completed component
checks and outstanding integration acceptance. It is not a production PCB
certification. The observations below describe separate commands that actually
completed during development. They are not a claim that the final archive was
run through every check in one uninterrupted release run.

## Completed development checks

| Check | Actual outcome | Boundary |
| --- | --- | --- |
| Existing local suite | 75 passed, 4 external checks skipped, 8 unittest subtests passed | Core schema, mocked API transport, geometry/router, property, transaction, installer and subprocess tests |
| New finishing suite | 20 passed | Labels, locks, source preservation, protobuf updates, profile validation and fabrication refusal behavior |
| Corrected finishing and native suite | 22 passed, 3 deselected | The 20 finishing cases plus both actual KiCad CLI integration cases |
| Desktop integration | 1 passed, 4 deselected | Real Tk window, worker result, canvas controls, reference-label preview/export and disabled native actions in demo mode |
| Ruff formatting and lint | Passed before final documentation edits | Source formatting and imports; no intentionally suppressed reported errors |

The 22-case command includes the same 20 finishing cases; do not add those
counts twice. The earlier existing-suite run preceded the final fabrication
hardening. These separate runs establish the stated boundaries, not a final
all-tests or all-platforms pass. Observed counts are preserved in
[validation/report.json](validation/report.json).

Reference execution used Linux x86-64, Python 3.12.14, Tk 9.0 on an Xvfb virtual
display, and real KiCad 10.0.6 CLI/bundled fixture Python. Runtime pins:
`openai==2.54.0`, `kicad-python==0.8.0`, `shapely==2.1.2`, `numpy==2.3.5`,
`jsonschema==4.26.0`. API transport tests use the SDK with a simulated HTTP
response; adapter tests use actual protobuf wrappers with a simulated server.
The native CLI tests use the actual KiCad process. Large third-party runtimes
are not included in this archive.

## Native experiments that passed

The route test generates a rectangular disposable board with two SIGNAL pads
and an independent GND pad. The local router connects SIGNAL using 0.25 mm
copper. Native DRC must show fewer unconnected items without new violations.
The negative control anchors GND copper to its pad and crosses SIGNAL; it must
produce an actual native electrical error, not only a dangling-track warning.

The finishing test generates three local reference-label operations and applies
them through the fixture generator to the real native board. The fabrication
pipeline runs the actual CLI, refills zones, strengthens project minima and
exports Gerber X2, Excellon/placement and SVG reference outputs. The positive
fixture has **zero remaining DRC items**. Its ZIP integrity, expected seven
Gerber files and placement CSV are checked; source hashes remain unchanged.

Negative controls increase the track minimum to 0.4 mm and the reference-text
minimum to 2.0 mm. Both block export and report the expected native violation
types. The saved fixture initially ignores track-width/text-height checks;
KiCad Astra reenables them on its isolated copy. A clean result requires the
native report to contain no ignored checks. The test verifies this behavior.

Native tests exposed and corrected two issues: SVG needs explicit
`--mode-multi`, and KiCad's text minima are `rules.min_text_height` and
`rules.min_text_thickness`. The negative controls passed after correction.
These fixtures are synthetic geometry, not functional electronic products.
Schematic parity is disabled only in the synthetic fabrication fixture, which
contains no circuit schematic. The default user profile requires parity.

## Final rerun status and remaining work

**The final combined release verification was not executed.** Automatic
approval review rejected dependency/native-runtime setup after the account's
usage limit was reached. The setup was not bypassed. No fresh combined JUnit
or coverage result is claimed, and no previous release's coverage percentage
is reused. Local syntax, installer and archive-integrity checks are recorded
separately under `packaging_checks` in the report.

Still required before relying on normal project editing or fabrication:

- Live KiCad IPC preview/rollback and manual Apply, Save and one-step Undo.
- A live hosted-model call using an account with the selected model's access.
- Installation/discovery on the user's actual Windows/macOS/Linux setup.
- The GitHub CI matrix after the repository is uploaded; included workflow
  files have not already run on GitHub.
- Real-board schematic parity, custom rules, external hierarchy dependencies,
  zones, drills/slots, backside assembly and fabricator-specific review.
- Electrical, thermal, mechanical and assembly review, including a verified
  BOM/MPNs, component orientation, polarity and actual product labels.

The plugin does not implement controlled-impedance/differential-pair routing,
length tuning, electrical/thermal simulation, arbitrary vendor DFM or automatic
assembly signoff. See [ROADMAP.md](ROADMAP.md). `assembly_ready` remains false,
and fabrication outputs are explicitly marked `exported_for_review`.

## Reproduce the checks

Follow the complete platform setup in [README.md](README.md), install
`requirements-dev.txt` in that Python environment, and run:

```bash
python scripts/verify.py
python scripts/verify.py --gui --native-cli
python scripts/verify.py --gui --native-cli --native --live-api --require-all
```

Use the environment's executable, such as `.\.venv\Scripts\python.exe` on
Windows or `.venv/bin/python` on Linux/macOS. The first command needs no API
key or KiCad and explicitly skips external checks. Native CLI tests require
`KICAD_ASTRA_KICAD_CLI` and `KICAD_ASTRA_KICAD_PCBNEW_PYTHON`; the latter must
be the matching KiCad interpreter capable of importing its bundled `pcbnew`.
That legacy module generates fixtures only; runtime editing uses IPC.

For `--native`, generate a disposable fixture with
`scripts/generate_native_fixture.py`, open its saved project in PCB Editor,
and provide normal IPC access. `--gui` requires a desktop. `--live-api`
explicitly opts into a potentially billed request on synthetic data and needs
`OPENAI_API_KEY`. Do not run the native fixture test on a production board.

The verifier writes current logs, JUnit, native fixtures/DRC evidence, coverage
and `report.json` under `build/verification/`. Its `--require-all` option fails
when any integration case is skipped. Saved observations in `validation/` do
not update themselves when you run it.

## KiCad Astra 1.0 packaging update

The rename and UI styling update passed Python syntax, JSON parsing, local Markdown path checks and isolated installer/upgrade checks. Runtime tests could not be rerun because the previous environment interpreter and pytest are unavailable. Earlier runtime observations below apply to the pre-rename development build; they do not establish acceptance of this final archive.
