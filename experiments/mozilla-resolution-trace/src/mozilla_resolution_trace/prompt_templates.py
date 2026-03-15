from __future__ import annotations

import json
from typing import Iterable, List


SYSTEM_CONSTRAINTS = (
    "You are evaluating bug-resolution evidence.\n"
    "Use only the provided artifact snippets.\n"
    "Do not infer beyond the evidence.\n"
    "Do not invent missing debugging steps.\n"
    "If evidence is insufficient, return not_supported.\n"
    "If support is partial, return weakly_supported.\n"
    "Return strict JSON only."
)


def milestone_disambiguation_prompt(
    artifact: dict,
    candidates: Iterable[str],
    neighboring_milestones: List[str],
) -> str:
    return json.dumps(
        {
            "task": "milestone_disambiguation",
            "artifact": artifact,
            "neighboring_milestones": neighboring_milestones,
            "candidates": list(candidates),
            "return_json": {
                "results": [
                    {
                        "candidate_milestone": "string",
                        "verdict": "supported | weakly_supported | not_supported",
                        "confidence": "high | medium | low",
                        "evidence_indices": [0],
                        "rationale": "string",
                    }
                ]
            },
        },
        ensure_ascii=True,
    )


def cross_artifact_synthesis_prompt(
    artifacts: List[dict],
    candidates: Iterable[str],
    neighboring_milestones: List[str],
    repair_mode: bool,
) -> str:
    return json.dumps(
        {
            "task": "cross_artifact_synthesis",
            "repair_mode": repair_mode,
            "neighboring_milestones": neighboring_milestones,
            "candidates": list(candidates),
            "artifacts": artifacts,
            "return_json": {
                "results": [
                    {
                        "candidate_milestone": "string",
                        "verdict": "supported | weakly_supported | not_supported",
                        "confidence": "high | medium | low",
                        "evidence_indices": [0, 1],
                        "rationale": "string",
                    }
                ]
            },
        },
        ensure_ascii=True,
    )


def shallow_trace_repair_prompt(
    trace_summary: dict,
    artifacts: List[dict],
    candidates: Iterable[str],
) -> str:
    return json.dumps(
        {
            "task": "shallow_trace_repair",
            "trace_summary": trace_summary,
            "candidates": list(candidates),
            "artifacts": artifacts,
            "return_json": {
                "results": [
                    {
                        "candidate_milestone": "string",
                        "verdict": "supported | weakly_supported | not_supported",
                        "confidence": "high | medium | low",
                        "evidence_indices": [0, 1],
                        "rationale": "string",
                    }
                ]
            },
        },
        ensure_ascii=True,
    )


def information_priority_prompt(
    milestone_type: str,
    requirements: List[dict],
    artifacts: List[dict],
) -> str:
    return json.dumps(
        {
            "task": "information_priority_labeling",
            "milestone_type": milestone_type,
            "requirements": requirements,
            "artifacts": artifacts,
            "return_json": {
                "results": [
                    {
                        "requirement_id": "string",
                        "priority_level": "critical | important | contextual",
                        "confidence": "high | medium | low",
                        "rationale": "string",
                    }
                ]
            },
        },
        ensure_ascii=True,
    )
