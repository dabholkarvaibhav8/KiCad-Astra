# KiCad Astra project structure

Keep this folder layout when uploading the repository. The repository root is
the folder that directly contains `README.md`, `plugin.json` and `main.py`.
There should be no additional `kicad-astra/` parent inside that root.

## Root layout

| Location | Contents |
| --- | --- |
| Repository root | Entry point, KiCad manifest, dependencies, profiles, README, license and project guides |
| `agent/` | Hosted planner, schema and measured repair workflow |
| `kicad/` | Capture, geometry, checks, native operations and fabrication |
| `ui/` | Desktop workbench and board preview |
| `support/` | Version identity and diagnostics |
| `examples/` | Synthetic board and offline route example |
| `scripts/` | Installer, fixture generator, verifier and archive builder |
| `tests/` | Behavior, property, adapter, process and integration tests |
| `icons/` | Plugin icon assets |
| `docs/` | Technical references and README artwork |
| `validation/` | Recorded observations and documentation/package checks |
| `.github/` | CI and issue/pull-request templates |

## Every source file

All paths below are relative to the repository root. Upload the complete source
set, including GitHub metadata. Python package marker files are intentional.

| File | Purpose |
| --- | --- |
| [.gitattributes](.gitattributes) | Normalize source line endings while preserving binary files. |
| [.github/ISSUE_TEMPLATE/bug_report.yml](.github/ISSUE_TEMPLATE/bug_report.yml) | Collect reproducible environment, failure and diagnostics details. |
| [.github/ISSUE_TEMPLATE/feature_request.yml](.github/ISSUE_TEMPLATE/feature_request.yml) | Collect an engineering use case and observable acceptance criteria. |
| [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) | Capture the problem, change and exact validation evidence. |
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | Run Python verification and build artifacts on three OS runners after upload. |
| [.gitignore](.gitignore) | Exclude environments, credentials, generated output and local files from Git. |
| [CHANGELOG.md](CHANGELOG.md) | Version 1.0 changes and verification boundaries. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, change contracts and contribution expectations. |
| [GITHUB_LAUNCH.md](GITHUB_LAUNCH.md) | Public repository upload, versioned release and download instructions. |
| [LICENSE](LICENSE) | MIT license for this project code. |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | Complete file inventory and repository-root layout. |
| [README.md](README.md) | Start here: download, setup, workflow, development and troubleshooting. |
| [ROADMAP.md](ROADMAP.md) | Implemented scope, outstanding acceptance and planned capabilities. |
| [VALIDATION.md](VALIDATION.md) | Actual observed test runs and remaining integration work. |
| [agent/__init__.py](agent/__init__.py) | Optional hosted-model planning for KiCad Astra. |
| [agent/astra_client.py](agent/astra_client.py) | Bounded Responses API requests with explicit incomplete/refusal handling. |
| [agent/prompts.py](agent/prompts.py) | Board facts, user goals, constraints and measured feedback stay distinct. |
| [agent/tools.py](agent/tools.py) | Strict model schema; routing endpoints are real pad UUIDs, never invented coordinates. |
| [agent/workflow.py](agent/workflow.py) | Bounded plan → geometry/router → measured revision workflow. |
| [constraints.example.json](constraints.example.json) | Layout defaults: dimensions, fixed/manual items and routing budgets. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Data flow, protocol, geometry, routing, API repair and native transaction contracts. |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every layout setting, unit, default, limit and constraint example. |
| [docs/FINISHING_AND_FABRICATION.md](docs/FINISHING_AND_FABRICATION.md) | Label geometry, native field updates, profile mappings and fabrication output contract. |
| [docs/TESTING.md](docs/TESTING.md) | Test groups, native fixture setup, external checks, acceptance and release build. |
| [docs/assets/kicad-astra-header.svg](docs/assets/kicad-astra-header.svg) | KiCad Astra vector header displayed on the repository homepage. |
| [examples/__init__.py](examples/__init__.py) | Synthetic demo data. No real electronic design is implied. |
| [examples/demo_scene.py](examples/demo_scene.py) | Reproducible offline scene for previewing and testing the local engine. |
| [examples/run_offline.py](examples/run_offline.py) | Run the synthetic routing example without a desktop, KiCad, or network. |
| [icons/kicad-astra.png](icons/kicad-astra.png) | Raster toolbar icon referenced by the KiCad manifest. |
| [icons/kicad-astra.svg](icons/kicad-astra.svg) | Vector source for the toolbar icon. |
| [kicad/__init__.py](kicad/__init__.py) | KiCad IPC integration and deterministic board operations. |
| [kicad/board_reader.py](kicad/board_reader.py) | PCB snapshot with KiCad-supplied pad polygons and conservative obstacles. |
| [kicad/config.py](kicad/config.py) | Explicit design constraints; these are user settings, not fabrication guarantees. |
| [kicad/drc.py](kicad/drc.py) | Native DRC on isolated board/project copies, with cancellation and regression diff. |
| [kicad/geometry.py](kicad/geometry.py) | Geometry in board millimetres. Curves are sampled with a bounded chord error. |
| [kicad/labels.py](kicad/labels.py) | Deterministic reference-label arrangement with native DRC as final geometry gate. |
| [kicad/manufacturing.py](kicad/manufacturing.py) | Strict native fabrication preflight and isolated output preparation. |
| [kicad/placement.py](kicad/placement.py) | Native footprint edits without dropping non-geometric children. |
| [kicad/quality.py](kicad/quality.py) | Inspectable geometry metrics, without a misleading universal quality score. |
| [kicad/router.py](kicad/router.py) | Bounded multi-layer A*: exact collision tests, real pad endpoints, through-vias. |
| [kicad/routing.py](kicad/routing.py) | Native copper construction with stable UUIDs for preview/apply equivalence. |
| [kicad/transactions.py](kicad/transactions.py) | Preview and apply the same native operations; each preview is rolled back immediately. |
| [kicad/validation.py](kicad/validation.py) | Deterministic geometry and connectivity checks. KiCad DRC is a separate gate. |
| [labels.example.json](labels.example.json) | Reference-text dimensions, spacing and candidate search defaults. |
| [main.py](main.py) | KiCad entry point for the KiCad Astra layout assistant. |
| [manufacturing.example.json](manufacturing.example.json) | Generic fabrication profile; replace limits with verified project/process requirements. |
| [plugin.json](plugin.json) | KiCad IPC plugin identity, runtime, action and icon registration. |
| [pyproject.toml](pyproject.toml) | Ruff, pytest markers and coverage configuration. |
| [requirements-dev.txt](requirements-dev.txt) | Runtime requirements plus test, lint and coverage tools. |
| [requirements.txt](requirements.txt) | Pinned Python runtime dependencies. |
| [scripts/__init__.py](scripts/__init__.py) | Development entry points; importing this package performs no work. |
| [scripts/build_release.py](scripts/build_release.py) | Build a source archive with deterministic entries and SHA-256 manifest. |
| [scripts/generate_native_fixture.py](scripts/generate_native_fixture.py) | Run with KiCad's pcbnew-enabled Python; create disposable CLI test boards. |
| [scripts/install_plugin.py](scripts/install_plugin.py) | Install a source release atomically, retaining an upgrade backup. |
| [scripts/verify.py](scripts/verify.py) | Run release checks and write a machine-readable readiness report. |
| [support/__init__.py](support/__init__.py) | KiCad Astra product identity and compatibility floor. |
| [support/doctor.py](support/doctor.py) | Read-only diagnostics with explicit pass/fail/not_run states. |
| [tests/__init__.py](tests/__init__.py) | Offline tests for KiCad Astra. |
| [tests/test_agent_tools.py](tests/test_agent_tools.py) | Package marker for tests. |
| [tests/test_finishing.py](tests/test_finishing.py) | Behavior tests for reference labels and isolated fabrication preparation. |
| [tests/test_hardening.py](tests/test_hardening.py) | Boundary, repair, installation, and real subprocess regression tests. |
| [tests/test_integration.py](tests/test_integration.py) | Opt-in external checks; skipped checks are never recorded as passes. |
| [tests/test_native_adapter.py](tests/test_native_adapter.py) | Exercise real kicad-python protobuf wrappers with a simulated IPC server. |
| [tests/test_properties.py](tests/test_properties.py) | Geometric invariants tested across generated layouts and transforms. |
| [tests/test_router.py](tests/test_router.py) | Package marker for tests. |
| [tests/test_transactions.py](tests/test_transactions.py) | Failures at the native edit/DRC boundary must not leave partial board edits. |
| [tests/test_validation.py](tests/test_validation.py) | Package marker for tests. |
| [ui/__init__.py](ui/__init__.py) | Desktop user interface for KiCad Astra. |
| [ui/assistant_panel.py](ui/assistant_panel.py) | Desktop planning workbench. Worker threads communicate only through a queue. |
| [ui/board_preview.py](ui/board_preview.py) | Interactive physical preview: layer filter, proposed overlays, pan, zoom and selection. |
| [validation/README.md](validation/README.md) | Explain provenance and scope of the saved verification records. |
| [validation/documentation-checks.json](validation/documentation-checks.json) | Current documentation, source-layout, installation and archive checks. |
| [validation/report.json](validation/report.json) | Observed separate development runs and earlier packaging outcomes. |

## Generated files and local folders

| Item | How to handle it |
| --- | --- |
| Root `SHA256SUMS.json` | Generated into the release ZIP; excluded from Git so later commits do not retain stale checksums |
| `dist/kicad-astra-v1.0.0.zip` | Built release asset; attach to GitHub Releases |
| `.venv/` | Local Python environment; each user creates their own |
| `build/verification/` | Fresh test logs, reports, coverage and generated native evidence |
| `demo-session.json` | Output of the headless example |
| Board/plugin backups | Keep with your own installation/project; do not publish private designs |
| Fabrication output folders | Review against the specific board; keep production outputs separate from this tool's source |

The release builder includes the complete source set above plus its checksum
manifest. The KiCad installer copies the runtime, examples, tests and documents
it needs; GitHub metadata remains part of the source repository. No model
weights, Python environment, KiCad binaries or production board are bundled.

## Upload and download flow

1. Extract the source ZIP and open the folder containing `plugin.json`.
2. Upload/commit that folder's **contents** to a public repository root.
3. Confirm GitHub displays the KiCad Astra README and its header.
4. Build a fresh ZIP and attach it to a versioned prerelease.
5. Visitors download the asset, extract it and follow the README setup.

Use [GITHUB_LAUNCH.md](GITHUB_LAUNCH.md) for the browser steps and release fields.
