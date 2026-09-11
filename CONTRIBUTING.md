# Contributing to KiCad Astra

Start with one reproducible engineering problem and a small disposable board.
Report the board version, units, stackup, affected items, expected result and
native DRC output. Never attach a customer design or credential without the
right to share it.

## Development environment

Use Python 3.12. From the repository root on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/verify.py
```

On Linux/macOS replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`
after `python3 -m venv .venv`. Tkinter must be provided by that interpreter.
The default checks require neither an API key nor KiCad. External checks are
explicitly skipped until enabled; see [README.md](README.md) for the options.

Run formatting before the verifier:

```bash
python -m ruff format .
python -m ruff check .
python scripts/verify.py
```

Use the environment's Python for these commands. Keep a focused change and
add a behavior test when it resolves a concrete regression. For routing,
label or native mutation changes, include a native fixture and retain DRC
results. Passing a protobuf mock does not verify the editor implementation.

## Core contracts

- AI output contains schema-constrained intent; never executable commands.
- Native mutations require unchanged board/rules, validated operations,
  a fresh matching DRC receipt, a backup and rollback on failure.
- All native adapter return values must be checked for partial/clamped edits.
- Labels preserve component pose, pads, nets, locked items and hidden fields.
- Fabrication uses copied inputs, stronger-or-equal minima and zero reported
  DRC items. Failed exports cannot be presented as ready packages.
- GUI workers communicate through the event queue; Tk calls stay on its thread.
- Keep KiCad Astra as the product identity. Preserve accurate provider API
  identifiers, third-party names and license notices.

## Useful first contributions

Document a successful native Apply/Undo round trip on your operating system;
add a small backside-reference or dense-silkscreen fixture; test an installer
path containing spaces; improve a reproducible failure message. A focused
report with a minimal board is more useful than a broad rewrite.

## Pull requests and releases

Explain why the change is needed, resulting behavior and exact evidence.
CI runs Python checks on three OS runners after upload. It does not establish
live editor, API, or manufacturing approval. Review those separately on a
saved disposable project. Keep unsupported geometry explicit and update the
technical README when protocol or behavior changes.

For release preparation, run `scripts/build_release.py`, inspect the ZIP,
verify its SHA-256 manifest, update `VALIDATION.md`, and publish a prerelease
while external acceptance remains incomplete. Never commit keys, local
backups, customer boards or generated production exports. The existing MIT
license governs contributed project code.
