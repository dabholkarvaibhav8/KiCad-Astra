# KiCad Astra testing and release checks

Run commands from the repository root with its environment Python. Actual
development observations and outstanding checks are recorded in
[VALIDATION.md](../VALIDATION.md). They are separate runs, not a final combined
pass. This guide describes how to produce fresh results on your machine.

## Development and verification

Run commands with `.venv/bin/python` on Linux/macOS or
`.\.venv\Scripts\python.exe` on Windows; `python` below is shorthand for it.

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python scripts/verify.py
```

The runner records compile/lint/format/test exit codes, JUnit cases, branch
coverage, and an explicit readiness report in `build/verification/`. Each run
removes previous JUnit/coverage output. Default verification can succeed while
external tests are skipped; `readiness_gate_passed` remains false until every
registered integration check ran successfully. `--require-all` makes skipped
checks fail the command as well. This gate covers the included automated
checks, not every real-board feature or manufacturing qualification.

| Test group | What it exercises |
| --- | --- |
| Schema/API transport | Actual SDK request serialization with mocked HTTP; strict output, refusal/incomplete responses, numeric and duplicate-key rejection |
| Geometry/placement | Outlines/cutouts, transforms, courtyards, pad/drill/copper constraints, attached items, locks and explicit constraints |
| Router | Obstacles, exact endpoints, width floors, vias/hidden layers, deterministic IDs, cancellation and constrained search |
| Property tests | Generated obstacle positions and rigid-transform round trips with deterministic Hypothesis settings |
| Native adapter | Real `kicad-python` wrapper serialization with a simulated server |
| Transaction regressions | Failed/partial staging, rollback, stale fingerprints, changed constraints, candidate mismatch, backups and receipt reuse |
| Process boundary | Actual child processes for timeout/cancellation/reaping, malformed/missing/stale DRC output, cross-process lock exclusion |
| Installer/diagnostics | Upgrade backup, foreign-folder refusal, dry-run, invalid settings, key redaction |
| Opt-in integration | Real Tk interaction, native CLI DRC, live editor preview/rollback, synthetic live API generation |

### Native CLI integration test

This test uses a disposable generated board. It verifies that locally compiled
copper reduces an unconnected item without adding DRC issues, then introduces
a deliberate short and verifies that native DRC detects it. A second native
test arranges three labels, exports fabrication files, and proves that stricter
track/text limits block output even when those DRC checks were initially ignored.

Set `KICAD_ASTRA_KICAD_CLI` to the installed `kicad-cli` and
`KICAD_ASTRA_KICAD_PCBNEW_PYTHON` to a Python interpreter from that KiCad installation
that can execute `import pcbnew`. This legacy module is used **only to generate
test fixtures**. The plugin's runtime editing API is IPC through `kicad-python`.
Do not install an unrelated package named `pcbnew` from a registry.

```bash
python scripts/verify.py --native-cli
```

In PowerShell, assign test paths using `$env:KICAD_ASTRA_KICAD_CLI = 'C:\actual\path\kicad-cli.exe'`
and `$env:KICAD_ASTRA_KICAD_PCBNEW_PYTHON = 'C:\actual\path\python.exe'`. Paths depend
on the KiCad installation. The runner preserves board/project files and JSON
DRC evidence under its output directory.

### Desktop, editor, and API integration

```bash
python scripts/verify.py --gui
python scripts/verify.py --native
python scripts/verify.py --live-api
python scripts/verify.py --gui --native-cli --native --live-api --require-all
```

`--gui` requires a display and exercises the actual demo canvas, selection,
layer/overlay controls, reference-label preview/export, and disabled native actions.

Before `--native`, generate the disposable fixture with KiCad's Python:

```bash
/path/to/kicad-python scripts/generate_native_fixture.py --output /path/to/disposable-fixture
```

Open `kicad-astra-native-fixture.kicad_pcb` as a saved project in KiCad and run the
check with the correct IPC access. The test rejects any other board filename,
previews a small U1 move, runs native DRC, drops the temporary commit, and
compares the restored snapshot. It does not apply/save edits to your design.
The automated native test covers preview/rollback; verify Apply and one-step
Undo manually on this fixture before using normal boards.

`--live-api` requires `OPENAI_API_KEY` and explicitly opts into a potentially
billed generation request on **synthetic data**. It checks that Review mode
returns a valid proposal without changes. A successful metadata doctor check
does not replace this test.

### Manual desktop acceptance

On a disposable saved project: compare capture with the editor; inspect a
placement and route preview; confirm failed DRC blocks Apply; edit the live
board after a successful preview and confirm stale-plan rejection; recapture,
check and apply a valid plan; verify dimensions/nets and one-step Undo; inspect
backup/audit files; rerun the editor's DRC. Repeat for your project's actual
zones, stackup, custom rules, pad styles, and footprint families.

## Build and inspect a release

```bash
python scripts/build_release.py --output dist/kicad-astra-v1.0.0.zip
```

The builder sorts entries, uses fixed ZIP timestamps, excludes environments,
cache/build directories and symlinks, validates the archive, and includes
`SHA256SUMS.json` containing each included file's SHA-256. It prints the ZIP's
SHA-256 too. Identical source bytes with the same Python/compression environment
produce identical archives. Published test evidence changes archive bytes.
The manifest detects accidental changes; it is not a signed authenticity proof.

Before distributing a build, inspect its file list and keep project designs,
API keys and unrelated files out of the source tree. Dependency installation
still requires package access unless you separately prepare an offline wheel
set for the target operating system.
