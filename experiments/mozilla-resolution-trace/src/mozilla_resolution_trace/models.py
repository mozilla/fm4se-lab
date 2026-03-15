from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class Evidence:
    source_type: str
    source_identifier: str
    timestamp: Optional[str]
    normalized_summary: str
    raw_snippet: Optional[str] = None
    inferred: bool = False


@dataclass
class Artifact:
    artifact_type: str
    identifier: str
    timestamp: Optional[str]
    content: Dict[str, Any]


@dataclass
class RelatedBugContext:
    bug_id: str
    relation_type: str
    title: str
    status: str
    resolution: Optional[str]
    summary: str
    comments_count: int
    attachments_count: int
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class MilestoneSignal:
    signal_id: str
    milestone_type: str
    timestamp: Optional[str]
    evidence: List[Evidence]
    confidence: str
    observed: bool = True
    consumed: bool = False


@dataclass
class InformationRequirement:
    requirement_id: str
    description: str
    accepted_source_types: List[str]
    source_strategy: str = "artifact_lookup"
    priority_level: str = "important"
    rationale: Optional[str] = None
    creation_action: Optional[str] = None
    blocking: bool = True


@dataclass
class GatheredInformation:
    candidate_type: str
    items: List[Evidence] = field(default_factory=list)


@dataclass
class InformationNeed:
    need_id: str
    description: str
    required_for_milestone: str
    status: str
    source_strategy: str
    evidence: List[Evidence] = field(default_factory=list)
    creation_action: Optional[str] = None
    blocking: bool = True


@dataclass
class SufficiencyAssessment:
    candidate_type: str
    label: str
    rationale: str


@dataclass
class MilestoneCandidate:
    candidate_id: str
    milestone_type: str
    timestamp: Optional[str]
    requirements: List[InformationRequirement] = field(default_factory=list)
    supporting_signals: List[MilestoneSignal] = field(default_factory=list)


@dataclass
class Gap:
    gap_id: str
    category: str
    related_candidate_type: str
    description: str
    recoverable: bool = False
    missing_requirement_ids: List[str] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class Inference:
    inference_id: str
    statement: str
    confidence: str = "medium"
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class Milestone:
    milestone_id: str
    milestone_type: str
    timestamp: Optional[str]
    construction_status: str
    confidence: str
    evidence: List[Evidence] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class Transition:
    from_milestone: str
    to_milestone: str
    candidate_milestones_considered: List[str]
    selected_candidate: str
    required_information: List[InformationRequirement]
    information_needs: List[InformationNeed]
    available_information: List[InformationNeed]
    recoverable_information: List[InformationNeed]
    missing_information: List[InformationNeed]
    information_creation_actions: List[str]
    gathered_information: GatheredInformation
    sufficiency_assessment: SufficiencyAssessment
    recovered_information: List[Evidence]
    inferred_information: List[Inference]
    unresolved_gaps: List[Gap]
    evidence: List[Evidence]
    selection_rationale: str
    information_priority: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TraceQualityAssessment:
    completeness_score: float
    artifact_diversity_score: float
    evidence_density: float
    administrative_noise_ratio: float
    inferred_milestone_ratio: float
    overall_quality_label: str
    quality_notes: List[str] = field(default_factory=list)


@dataclass
class BugResolutionTrace:
    bug_id: str
    title: str
    summary: str
    candidate_milestone_types: List[str]
    derived_milestone_trace: List[Milestone]
    transitions: List[Transition]
    unresolved_gaps: List[Gap]
    inferred_information: List[Inference]
    related_bug_contexts: List[RelatedBugContext]
    final_resolution_summary: str
    trace_quality_assessment: TraceQualityAssessment


def parse_timestamp(value: Optional[str]) -> datetime:
    if isinstance(value, (list, tuple)) and value:
        try:
            return datetime.fromtimestamp(float(value[0]), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return datetime.min
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return datetime.min
    if not value:
        return datetime.min
    if not isinstance(value, str):
        return datetime.min
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min


def normalize_timestamp(value: Any) -> Optional[str]:
    parsed = parse_timestamp(value)
    if parsed == datetime.min:
        if isinstance(value, str):
            return value
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
