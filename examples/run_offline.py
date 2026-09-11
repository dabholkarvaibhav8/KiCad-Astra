"""Run the synthetic routing example without a desktop, KiCad, or network."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.workflow import evaluate
from examples.demo_scene import DemoSession, demo_proposal
from kicad.config import LayoutRules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write an importable demo session JSON")
    args = parser.parse_args()
    bundle = evaluate(demo_proposal(), DemoSession().capture(), LayoutRules(), "routing")
    print(bundle.report.as_text())
    if args.output:
        args.output.write_text(
            json.dumps(bundle.to_dict(), indent=2, allow_nan=False), encoding="utf-8"
        )
        print(f"Wrote {args.output}")
    return 0 if bundle.report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
