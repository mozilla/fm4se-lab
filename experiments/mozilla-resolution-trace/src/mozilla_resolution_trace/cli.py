from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path
from typing import List

from .bugzilla_client import BugzillaClient
from .llm_refiner import LLMTraceRefiner, OpenAICompatibleLLMClient
from .resolution_trace_builder import ResolutionTraceBuilder
from .serializer import TraceSerializer

try:
    from urllib3.exceptions import NotOpenSSLWarning
except ImportError:  # pragma: no cover
    NotOpenSSLWarning = None


DEFAULT_RESULTS_DIR = Path("results")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mozilla bug-resolution reconstruction pipeline")
    parser.add_argument("--bug-id", type=int, help="Bugzilla bug ID")
    parser.add_argument("--bug-url", type=str, help="Bugzilla bug URL")
    parser.add_argument("--bug-ids", type=int, nargs="+", help="Multiple Bugzilla bug IDs")
    parser.add_argument("--bug-file", type=Path, help="File containing bug IDs or Bugzilla URLs, one per line")
    parser.add_argument("--output", type=Path, help="Optional output JSON file path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="Directory for batch outputs")
    parser.add_argument("--max-steps", type=int, default=100, help="Maximum transitions to attempt")
    parser.add_argument(
        "--format",
        choices=["concise", "verbose"],
        default="concise",
        help="JSON output format",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["off", "assist"],
        default="assist",
        help="Optional hybrid mode that lets an LLM propose extra evidence-backed milestone signals.",
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        help="Model name for --llm-mode assist.",
    )
    return parser


def resolve_bug_ids(args: argparse.Namespace) -> List[int]:
    bug_ids: List[int] = []

    if args.bug_id is not None or args.bug_url:
        bug_ids.append(BugzillaClient.parse_bug_id(bug_id=args.bug_id, bug_url=args.bug_url))

    if args.bug_ids:
        bug_ids.extend(int(bug_id) for bug_id in args.bug_ids)

    if args.bug_file:
        for raw_line in args.bug_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.isdigit():
                bug_ids.append(int(line))
            else:
                bug_ids.append(BugzillaClient.parse_bug_id(bug_url=line))

    deduped: List[int] = []
    seen = set()
    for bug_id in bug_ids:
        if bug_id in seen:
            continue
        seen.add(bug_id)
        deduped.append(bug_id)
    return deduped


def output_path_for_bug(args: argparse.Namespace, bug_id: int, multiple: bool) -> Path | None:
    if args.output and not multiple:
        return args.output
    if args.output and multiple:
        raise ValueError("--output can only be used for a single bug. Use --output-dir for batch runs.")
    return args.output_dir / f"bug_{bug_id}_trace.json"


def main() -> None:
    if NotOpenSSLWarning is not None:
        warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

    parser = build_parser()
    args = parser.parse_args()
    bug_ids = resolve_bug_ids(args)
    if not bug_ids:
        parser.error("Provide --bug-id, --bug-url, --bug-ids, or --bug-file.")

    llm_refiner = None
    if args.llm_mode == "assist":
        llm_refiner = LLMTraceRefiner(OpenAICompatibleLLMClient(model=args.llm_model))

    builder = ResolutionTraceBuilder(llm_refiner=llm_refiner, llm_mode=args.llm_mode)
    multiple = len(bug_ids) > 1

    for bug_id in bug_ids:
        trace = builder.build(bug_id=bug_id, max_steps=args.max_steps)
        payload = TraceSerializer.to_json(trace, output_format=args.format)
        output_path = output_path_for_bug(args, bug_id, multiple)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload, encoding="utf-8")
            if multiple:
                print(f"{bug_id}: {output_path}")
        else:
            print(payload)


if __name__ == "__main__":
    main()
