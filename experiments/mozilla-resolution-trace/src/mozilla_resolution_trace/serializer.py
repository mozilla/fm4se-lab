from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List


class TraceSerializer:
    @staticmethod
    def to_dict(trace: Any, output_format: str = "concise") -> dict:
        if not is_dataclass(trace):
            raise TypeError("TraceSerializer.to_dict expects a dataclass instance")

        raw = asdict(trace)
        if output_format == "verbose":
            return raw
        if output_format != "concise":
            raise ValueError(f"Unsupported output format: {output_format}")
        return TraceSerializer._to_concise_dict(raw)

    @staticmethod
    def to_json(trace: Any, indent: int = 2, output_format: str = "concise") -> str:
        return json.dumps(
            TraceSerializer.to_dict(trace, output_format=output_format),
            indent=indent,
            ensure_ascii=True,
        )

    @staticmethod
    def _to_concise_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
        milestones = raw.get("derived_milestone_trace", [])
        transitions = raw.get("transitions", [])

        return {
            "bug_id": raw.get("bug_id"),
            "title": raw.get("title"),
            "summary": raw.get("summary"),
            "final_resolution_summary": raw.get("final_resolution_summary"),
            "trace_quality_assessment": raw.get("trace_quality_assessment"),
            "candidate_milestone_types": raw.get("candidate_milestone_types", []),
            "trace_overview": {
                "milestone_count": len(milestones),
                "transition_count": len(transitions),
                "termination_reason": TraceSerializer._termination_reason(raw.get("unresolved_gaps", [])),
            },
            "derived_milestone_trace": [
                {
                    "milestone_id": milestone.get("milestone_id"),
                    "milestone_type": milestone.get("milestone_type"),
                    "timestamp": milestone.get("timestamp"),
                    "status": milestone.get("construction_status"),
                    "confidence": milestone.get("confidence"),
                    "why_it_exists": TraceSerializer._evidence_summaries(milestone.get("evidence", []), limit=2),
                }
                for milestone in milestones
            ],
            "transitions": [
                {
                    "from": transition.get("from_milestone"),
                    "to": transition.get("to_milestone"),
                    "selected": transition.get("selected_candidate"),
                    "considered": transition.get("candidate_milestones_considered", []),
                    "information_summary": {
                        "available": len(transition.get("available_information", [])),
                        "recoverable": len(transition.get("recoverable_information", [])),
                        "missing_and_needed": len(transition.get("missing_information", [])),
                    },
                    "needed": [
                        {
                            "requirement_id": requirement.get("requirement_id"),
                            "description": requirement.get("description"),
                            "priority_level": requirement.get("priority_level"),
                            "rationale": requirement.get("rationale"),
                            "blocking": requirement.get("blocking"),
                        }
                        for requirement in transition.get("required_information", [])
                    ],
                    "information_needs": [
                        {
                            "need_id": need.get("need_id"),
                            "need": need.get("description"),
                            "status": need.get("status"),
                            "blocking": need.get("blocking"),
                            "creation_action": need.get("creation_action"),
                            "evidence": [
                                {
                                    "source_type": item.get("source_type"),
                                    "source_identifier": item.get("source_identifier"),
                                    "raw_snippet": item.get("raw_snippet"),
                                    "inferred": item.get("inferred"),
                                }
                                for item in need.get("evidence", [])
                            ],
                        }
                        for need in transition.get("information_needs", [])
                    ],
                    "available_information": [
                        TraceSerializer._information_need_summary(need)
                        for need in transition.get("available_information", [])
                    ],
                    "recoverable_information": [
                        TraceSerializer._information_need_summary(need)
                        for need in transition.get("recoverable_information", [])
                    ],
                    "missing_information": [
                        TraceSerializer._information_need_summary(need)
                        for need in transition.get("missing_information", [])
                    ],
                    "support": (transition.get("sufficiency_assessment") or {}).get("label"),
                    "key_evidence": TraceSerializer._evidence_summaries(transition.get("evidence", []), limit=3),
                    "recovered": TraceSerializer._evidence_summaries(transition.get("recovered_information", []), limit=2),
                    "create_next": transition.get("information_creation_actions", []),
                    "rationale": transition.get("selection_rationale"),
                    "information_priority": transition.get("information_priority", []),
                }
                for transition in transitions
            ],
            "unresolved_gaps": [
                {
                    "gap_id": gap.get("gap_id"),
                    "category": gap.get("category"),
                    "candidate": gap.get("related_candidate_type"),
                    "description": gap.get("description"),
                    "recoverable": gap.get("recoverable"),
                    "missing": gap.get("missing_requirement_ids", []),
                    "evidence": [
                        {
                            "source_type": item.get("source_type"),
                            "source_identifier": item.get("source_identifier"),
                            "timestamp": item.get("timestamp"),
                            "normalized_summary": item.get("normalized_summary"),
                        }
                        for item in gap.get("evidence", [])
                    ],
                }
                for gap in raw.get("unresolved_gaps", [])
            ],
            "inferred_information": [
                {
                    "inference_id": inference.get("inference_id"),
                    "statement": inference.get("statement"),
                    "confidence": inference.get("confidence"),
                    "basis": TraceSerializer._evidence_summaries(inference.get("evidence", []), limit=2),
                }
                for inference in raw.get("inferred_information", [])
            ],
            "related_bug_contexts": [
                {
                    "bug_id": related.get("bug_id"),
                    "relation_type": related.get("relation_type"),
                    "title": related.get("title"),
                    "status": related.get("status"),
                    "resolution": related.get("resolution"),
                    "why_related": TraceSerializer._evidence_summaries(related.get("evidence", []), limit=2),
                }
                for related in raw.get("related_bug_contexts", [])
            ],
        }

    @staticmethod
    def _termination_reason(gaps: List[Dict[str, Any]]) -> str:
        if not gaps:
            return "trace_completed_without_recorded_gaps"
        return gaps[-1].get("description", "trace_stopped")

    @staticmethod
    def _evidence_summaries(evidence: Iterable[Dict[str, Any]], limit: int) -> List[str]:
        summaries: List[str] = []
        seen = set()
        for item in evidence:
            summary = item.get("normalized_summary")
            if not summary or summary in seen:
                continue
            seen.add(summary)
            summaries.append(summary)
            if len(summaries) >= limit:
                break
        return summaries

    @staticmethod
    def _information_need_summary(need: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "need_id": need.get("need_id"),
            "need": need.get("description"),
            "status": need.get("status"),
            "blocking": need.get("blocking"),
            "creation_action": need.get("creation_action"),
            "evidence_sources": [
                {
                    "source_type": item.get("source_type"),
                    "source_identifier": item.get("source_identifier"),
                    "inferred": item.get("inferred"),
                }
                for item in need.get("evidence", [])
            ],
        }
