from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional
import warnings
warnings.filterwarnings("ignore") 
from .reconstructor import MozillaTrajectoryReconstructor
from .zero_shot_compare import run_zero_shot_compare

def _load_env_file() -> None:
    # .env is expected at experiments/trajectory-reconstruction/.env
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconstruct Mozilla developer bug-fix trajectories from a Bugzilla ID."
    )
    parser.add_argument("--bug-id", type=int, required=False, help="Bugzilla bug ID (e.g., 2001809)")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="Directory where JSON and markdown outputs are written",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Write only JSON output (skip markdown report).",
    )
    parser.add_argument(
        "--zero-shot-compare",
        action="store_true",
        help="Run supplemented-context zero-shot fix generation and compare vs actual fix.",
    )
    parser.add_argument(
        "--trajectory",
        type=str,
        default="",
        help="Optional existing trajectory report path for zero-shot compare mode.",
    )
    return parser


def _prompt_bug_id() -> int:
    raw = input("Enter Bugzilla bug ID: ").strip()
    return int(raw)


def main(argv: Optional[list[str]] = None) -> int:
    _load_env_file()
    parser = build_parser()
    args = parser.parse_args(argv)

    bug_id = args.bug_id
    if not bug_id:
        try:
            bug_id = _prompt_bug_id()
        except (ValueError, KeyboardInterrupt):
            print("Invalid or cancelled bug ID input.")
            return 1

    out_dir = os.path.join(args.output_dir, str(bug_id))
    os.makedirs(out_dir, exist_ok=True)

    if args.zero_shot_compare:
        traj_path = args.trajectory if args.trajectory else os.path.join(out_dir, "trajectory_report.json")
        if not os.path.exists(traj_path):
            reconstructor = MozillaTrajectoryReconstructor()
            try:
                report = reconstructor.reconstruct(bug_id)
            except Exception as exc:
                print(f"Failed to reconstruct bug {bug_id}: {exc}")
                return 2
            with open(traj_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=True)
            print(f"Wrote {traj_path}")

        return run_zero_shot_compare(bug_id, Path(args.output_dir), Path(traj_path))

    reconstructor = MozillaTrajectoryReconstructor()

    try:
        report = reconstructor.reconstruct(bug_id)
    except Exception as exc:
        print(f"Failed to reconstruct bug {bug_id}: {exc}")
        return 2

    json_path = os.path.join(out_dir, "trajectory_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)
    print(f"Wrote {json_path}")

    if not args.raw_only:
        markdown = reconstructor.render_markdown(report)
        md_path = os.path.join(out_dir, "trajectory_report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"Wrote {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
