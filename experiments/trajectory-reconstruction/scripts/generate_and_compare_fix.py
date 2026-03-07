#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trajectory_reconstruction.zero_shot_compare import run_zero_shot_compare


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate zero-shot fix from supplemented bug+trajectory context and compare with actual fix."
    )
    parser.add_argument("--bug-id", type=int, required=True)
    parser.add_argument("--output-dir", type=str, default=str(ROOT / "results"))
    parser.add_argument("--trajectory", type=str, default="")
    args = parser.parse_args()

    traj_path = Path(args.trajectory) if args.trajectory else None
    return run_zero_shot_compare(args.bug_id, Path(args.output_dir), traj_path)


if __name__ == "__main__":
    raise SystemExit(main())
