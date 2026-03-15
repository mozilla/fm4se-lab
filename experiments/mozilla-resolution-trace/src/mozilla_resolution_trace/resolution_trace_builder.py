from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from .artifact_collector import ArtifactCollector, CollectedBugArtifacts
from .gap_recovery_engine import GapRecoveryEngine
from .information_gatherer import InformationGatherer
from .llm_refiner import LLMTraceRefiner
from .milestone_constructor import MilestoneConstructor
from .milestone_signal_extractor import MILESTONE_TYPE_LIBRARY, MilestoneSignalExtractor
from .models import (
    BugResolutionTrace,
    Gap,
    InformationNeed,
    Milestone,
    MilestoneCandidate,
    MilestoneSignal,
    RelatedBugContext,
    TraceQualityAssessment,
    Transition,
    parse_timestamp,
)
from .next_milestone_candidate_generator import NextMilestoneCandidateGenerator
from .sufficiency_evaluator import SufficiencyEvaluator
from .trace_state_manager import TraceStateManager
from .transition_requirement_analyzer import TransitionRequirementAnalyzer


MILESTONE_PROGRESS_RANK = {
    "Bug Reported": 0,
    "Clarification Requested": 1,
    "Reproduction Attempted": 2,
    "Reproduction Confirmed": 3,
    "Component Reassigned": 2,
    "Regression Identified": 4,
    "Regression Range Found": 5,
    "Root Cause Hypothesized": 6,
    "Root Cause Confirmed": 7,
    "Patch Proposed": 8,
    "Review Requested": 9,
    "Review Feedback Received": 10,
    "Patch Updated": 11,
    "Test Added": 12,
    "CI Failure Detected": 13,
    "CI Fix Applied": 14,
    "Fix Landed": 15,
    "Fix Backed Out": 16,
    "Fix Relanded": 17,
    "Verification Requested": 18,
    "Bug Resolved": 19,
    "Bug Reopened": 20,
    "Bug Closed": 21,
}

BACKTRACK_MILESTONE_TYPES = {"Bug Reopened", "Fix Backed Out"}
TECHNICAL_MILESTONE_TYPES = {
    "Reproduction Attempted",
    "Reproduction Confirmed",
    "Regression Identified",
    "Regression Range Found",
    "Root Cause Hypothesized",
    "Root Cause Confirmed",
    "Patch Proposed",
    "Patch Updated",
    "Review Requested",
    "Review Feedback Received",
    "Test Added",
    "CI Failure Detected",
    "CI Fix Applied",
    "Fix Landed",
    "Fix Backed Out",
    "Verification Requested",
    "Bug Resolved",
}
ADMINISTRATIVE_MILESTONE_TYPES = {"Component Reassigned", "Bug Reopened", "Bug Closed"}
MILESTONE_PREREQUISITES = {
    "Reproduction Confirmed": {"Bug Reported", "Clarification Requested", "Reproduction Attempted"},
    "Regression Identified": {"Bug Reported", "Reproduction Attempted", "Reproduction Confirmed"},
    "Regression Range Found": {"Regression Identified", "Reproduction Attempted", "Reproduction Confirmed"},
    "Root Cause Hypothesized": {"Reproduction Attempted", "Reproduction Confirmed", "Regression Identified", "Regression Range Found", "Component Reassigned"},
    "Root Cause Confirmed": {"Root Cause Hypothesized", "Regression Range Found", "Reproduction Confirmed"},
    "Patch Proposed": {"Reproduction Confirmed", "Root Cause Hypothesized", "Root Cause Confirmed", "Regression Range Found", "Review Feedback Received"},
    "Review Requested": {"Patch Proposed", "Patch Updated"},
    "Review Feedback Received": {"Review Requested", "Patch Proposed"},
    "Patch Updated": {"Patch Proposed", "Review Feedback Received", "CI Failure Detected"},
    "Test Added": {"Patch Proposed", "Patch Updated", "Fix Landed"},
    "CI Failure Detected": {"Patch Proposed", "Patch Updated", "Review Requested", "Fix Landed"},
    "CI Fix Applied": {"CI Failure Detected", "Patch Proposed", "Patch Updated"},
    "Fix Landed": {"Patch Proposed", "Patch Updated", "Review Requested", "Review Feedback Received", "CI Fix Applied", "Test Added"},
    "Fix Backed Out": {"Fix Landed"},
    "Fix Relanded": {"Fix Backed Out"},
    "Verification Requested": {"Fix Landed", "Bug Resolved"},
    "Bug Resolved": {"Fix Landed", "Patch Proposed", "Patch Updated", "Root Cause Confirmed", "Review Feedback Received"},
    "Bug Closed": {"Bug Resolved"},
}


@dataclass
class CandidateEvaluation:
    candidate: MilestoneCandidate
    gathered: object
    combined_gathered: object
    assessment: object
    missing_requirement_ids: List[str]
    recovered_information: List
    inferred_information: List
    information_needs: List[InformationNeed]


class ResolutionTraceBuilder:
    def __init__(
        self,
        collector: Optional[ArtifactCollector] = None,
        llm_refiner: Optional[LLMTraceRefiner] = None,
        llm_mode: str = "off",
    ):
        self.collector = collector or ArtifactCollector()
        self.extractor = MilestoneSignalExtractor()
        self.generator = NextMilestoneCandidateGenerator()
        self.requirements = TransitionRequirementAnalyzer()
        self.gatherer = InformationGatherer()
        self.evaluator = SufficiencyEvaluator()
        self.recovery = GapRecoveryEngine()
        self.constructor = MilestoneConstructor()
        self.llm_refiner = llm_refiner
        self.llm_mode = llm_mode
        self._gap_counter = 0

    def build(self, bug_id: int, max_steps: int = 100) -> BugResolutionTrace:
        artifacts = self.collector.collect(bug_id)
        trace = self._build_from_artifacts(artifacts, max_steps=max_steps, repair_mode=False)
        if self._needs_shallow_repair(trace):
            repaired = self._build_from_artifacts(artifacts, max_steps=max_steps, repair_mode=True)
            if self._is_trace_better(repaired, trace):
                repaired.trace_quality_assessment.quality_notes.append(
                    "Applied shallow-trace repair pass using linked artifacts and stronger technical milestone preference."
                )
                return repaired
            trace.trace_quality_assessment.quality_notes.append(
                "Shallow-trace repair pass checked linked artifacts but could not recover richer technical milestones."
            )
        return trace

    def _build_from_artifacts(
        self,
        artifacts: CollectedBugArtifacts,
        max_steps: int = 100,
        repair_mode: bool = False,
    ) -> BugResolutionTrace:
        title = artifacts.bug.content.get("summary", "")
        bug_summary = artifacts.bug.content.get("cf_user_story", "") or title

        signals = self.extractor.extract(artifacts)
        if self.llm_refiner is not None and self.llm_mode == "assist":
            signals = self.llm_refiner.adjudicate_signals(
                artifacts,
                signals,
                repair_mode=repair_mode,
                trace_summary=self._signal_trace_summary(signals),
            )
        initial = self._build_initial_milestone(signals)
        state = TraceStateManager(milestones=[initial], unresolved_gaps=list(artifacts.retrieval_gaps))

        step_count = 0
        while step_count < max_steps:
            step_count += 1
            current = state.current_milestone()
            candidates = self.generator.generate(current, signals)
            if not candidates:
                state.add_unresolved_gaps(
                    [
                        Gap(
                            gap_id=self._next_gap_id(),
                            category="trace_termination",
                            related_candidate_type="trace_termination",
                            description="Trace ended because no additional milestone candidate could be supported from remaining evidence.",
                            recoverable=False,
                        )
                    ]
                )
                break

            evaluations = [self._evaluate_candidate(candidate, artifacts, signals) for candidate in candidates]
            selected = self._select_best_candidate(evaluations, state, repair_mode=repair_mode)
            if not selected:
                state.add_unresolved_gaps(
                    [
                        Gap(
                            gap_id=self._next_gap_id(),
                            category="insufficient_temporal_evidence",
                            related_candidate_type="trace_termination",
                            description="Trace ended because no candidate satisfied the selection policy.",
                            recoverable=False,
                        )
                    ]
                )
                break

            selected_eval = selected
            unresolved_gaps = self._build_gaps(selected_eval)

            if selected_eval.assessment.label == "insufficient":
                state.add_unresolved_gaps(unresolved_gaps)
                break

            milestone_evidence = selected_eval.combined_gathered.items
            milestone = self.constructor.construct(
                selected_eval.candidate,
                selected_eval.assessment,
                milestone_evidence,
            )

            available_information = [need for need in selected_eval.information_needs if need.status == "available"]
            recoverable_information = [need for need in selected_eval.information_needs if need.status == "recoverable"]
            missing_information = [need for need in selected_eval.information_needs if need.status == "missing_and_needed"]

            information_priority = self._build_information_priority(selected_eval.candidate.requirements)
            if self.llm_refiner is not None and self.llm_mode == "assist":
                llm_priority = self.llm_refiner.label_information_priority(
                    selected_eval.candidate.milestone_type,
                    selected_eval.candidate.requirements,
                    milestone_evidence,
                    low_confidence=selected_eval.assessment.label != "sufficient" or repair_mode,
                )
                if llm_priority is not None:
                    information_priority = llm_priority

            transition = Transition(
                from_milestone=current.milestone_id,
                to_milestone=milestone.milestone_id,
                candidate_milestones_considered=[c.candidate.milestone_type for c in evaluations],
                selected_candidate=selected_eval.candidate.milestone_type,
                required_information=selected_eval.candidate.requirements,
                information_needs=selected_eval.information_needs,
                available_information=available_information,
                recoverable_information=recoverable_information,
                missing_information=missing_information,
                information_creation_actions=sorted(
                    {
                        need.creation_action
                        for need in missing_information
                        if need.creation_action
                    }
                ),
                gathered_information=selected_eval.gathered,
                sufficiency_assessment=selected_eval.assessment,
                recovered_information=selected_eval.recovered_information,
                inferred_information=selected_eval.inferred_information,
                unresolved_gaps=unresolved_gaps,
                evidence=milestone_evidence,
                selection_rationale=self._selection_rationale(selected_eval, evaluations),
                information_priority=information_priority,
            )

            state.add_milestone(milestone)
            state.add_transition(transition)
            state.add_unresolved_gaps(unresolved_gaps)
            state.add_inferences(selected_eval.inferred_information)
            state.consume_signals(selected_eval.candidate.supporting_signals)

        candidate_types = sorted({signal.milestone_type for signal in signals}, key=lambda t: MILESTONE_TYPE_LIBRARY.index(t) if t in MILESTONE_TYPE_LIBRARY else 999)
        summary = self._final_summary(state)
        related_bug_contexts = self._build_related_bug_contexts(artifacts)
        quality = self._trace_quality_assessment(state, artifacts)

        return BugResolutionTrace(
            bug_id=str(artifacts.bug_id),
            title=title,
            summary=bug_summary,
            candidate_milestone_types=candidate_types,
            derived_milestone_trace=state.milestones,
            transitions=state.transitions,
            unresolved_gaps=state.unresolved_gaps,
            inferred_information=state.inferred_information,
            related_bug_contexts=related_bug_contexts,
            final_resolution_summary=summary,
            trace_quality_assessment=quality,
        )

    def _evaluate_candidate(
        self,
        candidate: MilestoneCandidate,
        artifacts: CollectedBugArtifacts,
        signals: List[MilestoneSignal],
    ) -> CandidateEvaluation:
        candidate.requirements = self.requirements.requirements_for(candidate.milestone_type)
        gathered = self.gatherer.gather(candidate, signals)
        assessment, missing = self.evaluator.evaluate(candidate.milestone_type, candidate.requirements, gathered)

        recovered = []
        inferred = []
        combined_gathered = gathered
        if missing:
            recovered, inferred = self.recovery.recover(candidate, missing, artifacts)
            if recovered:
                combined_gathered = self._combine_gathered_information(candidate.milestone_type, gathered, recovered)
                assessment, missing = self.evaluator.evaluate(candidate.milestone_type, candidate.requirements, combined_gathered)

        information_needs = self._build_information_needs(
            candidate,
            candidate.requirements,
            gathered,
            recovered,
        )

        return CandidateEvaluation(
            candidate=candidate,
            gathered=gathered,
            combined_gathered=combined_gathered,
            assessment=assessment,
            missing_requirement_ids=missing,
            recovered_information=recovered,
            inferred_information=inferred,
            information_needs=information_needs,
        )

    def _select_best_candidate(
        self,
        evaluations: List[CandidateEvaluation],
        state: TraceStateManager,
        repair_mode: bool = False,
    ) -> Optional[CandidateEvaluation]:
        if not evaluations:
            return None

        eligible = [item for item in evaluations if self._is_candidate_allowed(item, state, repair_mode=repair_mode)]
        if not eligible:
            return None

        ranking = {"sufficient": 3, "partially sufficient": 2, "insufficient": 1}
        current_rank = MILESTONE_PROGRESS_RANK.get(state.current_milestone().milestone_type, -1)
        current_ts = state.current_milestone().timestamp

        def key_fn(item: CandidateEvaluation) -> Tuple[int, float, int, int, int, str]:
            candidate_rank = MILESTONE_PROGRESS_RANK.get(item.candidate.milestone_type, current_rank)
            progress_gap = max(candidate_rank - current_rank, 0)
            candidate_dt = item.candidate.timestamp
            time_gap = parse_timestamp(candidate_dt) - parse_timestamp(current_ts)
            time_gap_seconds = time_gap.total_seconds() if isinstance(time_gap, timedelta) else 0.0
            technical_bonus = 0 if item.candidate.milestone_type in TECHNICAL_MILESTONE_TYPES else 1
            admin_penalty = 2 if item.candidate.milestone_type in ADMINISTRATIVE_MILESTONE_TYPES else 0
            if repair_mode and item.candidate.milestone_type in ADMINISTRATIVE_MILESTONE_TYPES:
                admin_penalty += 4
            return (
                -ranking.get(item.assessment.label, 0),
                max(time_gap_seconds, 0.0),
                technical_bonus,
                admin_penalty,
                progress_gap,
                -len(item.combined_gathered.items),
                item.candidate.timestamp or "",
            )

        return sorted(eligible, key=key_fn)[0]

    def _build_initial_milestone(self, signals: List[MilestoneSignal]) -> Milestone:
        initial_signal = next((s for s in signals if s.milestone_type == "Bug Reported"), None)
        if not initial_signal:
            raise ValueError("Could not construct initial milestone: missing Bug Reported signal")
        initial_signal.consumed = True
        return Milestone(
            milestone_id="ms1",
            milestone_type="Bug Reported",
            timestamp=initial_signal.timestamp,
            construction_status="observed",
            confidence="high",
            evidence=initial_signal.evidence,
            notes="Initialized from bug creation metadata.",
        )

    def _build_gaps(self, evaluation: CandidateEvaluation) -> List[Gap]:
        if not evaluation.missing_requirement_ids:
            return []
        return [
            Gap(
                gap_id=self._next_gap_id(),
                category=self._gap_category(evaluation),
                related_candidate_type=evaluation.candidate.milestone_type,
                description="Missing required information for candidate milestone.",
                recoverable=bool(evaluation.recovered_information) or any(not need.evidence for need in evaluation.information_needs),
                missing_requirement_ids=evaluation.missing_requirement_ids,
                evidence=evaluation.gathered.items,
            )
        ]

    def _selection_rationale(self, selected: CandidateEvaluation, all_evals: List[CandidateEvaluation]) -> str:
        alternatives = [
            f"{item.candidate.milestone_type}:{item.assessment.label}"
            for item in all_evals
            if item.candidate.candidate_id != selected.candidate.candidate_id
        ]
        alt_text = "; alternatives=" + ", ".join(alternatives) if alternatives else ""
        return (
            f"Selected {selected.candidate.milestone_type} because support was {selected.assessment.label} "
            f"with {len(selected.combined_gathered.items)} evidence item(s).{alt_text}"
        )

    def _final_summary(self, state: TraceStateManager) -> str:
        types = [milestone.milestone_type for milestone in state.milestones]
        if len(types) == 1:
            return "Only initial reporting milestone could be established from available evidence."
        return " -> ".join(types)

    def _is_candidate_allowed(
        self,
        evaluation: CandidateEvaluation,
        state: TraceStateManager,
        repair_mode: bool = False,
    ) -> bool:
        milestone_type = evaluation.candidate.milestone_type
        current_type = state.current_milestone().milestone_type
        current_rank = MILESTONE_PROGRESS_RANK.get(current_type, -1)
        candidate_rank = MILESTONE_PROGRESS_RANK.get(milestone_type, -1)
        if evaluation.assessment.label == "insufficient":
            return False
        if milestone_type == current_type:
            return False
        if milestone_type in state.recent_milestone_types(2) and milestone_type not in {"Clarification Requested", "Review Feedback Received", "Patch Updated", "CI Failure Detected", "CI Fix Applied"}:
            return False
        if candidate_rank < current_rank and milestone_type not in BACKTRACK_MILESTONE_TYPES:
            return False
        if milestone_type == "Bug Closed" and not state.has_milestone_type("Bug Resolved"):
            return False
        if milestone_type == "Fix Relanded" and not state.has_milestone_type("Fix Backed Out"):
            return False
        if milestone_type == "Fix Backed Out" and not state.has_milestone_type("Fix Landed"):
            return False
        prerequisites = MILESTONE_PREREQUISITES.get(milestone_type)
        if prerequisites and not any(state.has_milestone_type(prereq) for prereq in prerequisites):
            if not self._repair_mode_allows_candidate(evaluation, state, repair_mode):
                return False
        if milestone_type in {"Bug Resolved", "Bug Closed"}:
            technical_seen = any(m.milestone_type in TECHNICAL_MILESTONE_TYPES for m in state.milestones)
            if not technical_seen and len(evaluation.combined_gathered.items) <= 2:
                return False
        return True

    def _repair_mode_allows_candidate(
        self,
        evaluation: CandidateEvaluation,
        state: TraceStateManager,
        repair_mode: bool,
    ) -> bool:
        if not repair_mode:
            return False

        source_types = {item.source_type for item in evaluation.combined_gathered.items}
        milestone_type = evaluation.candidate.milestone_type

        if milestone_type == "Patch Proposed":
            return bool(source_types & {"attachment", "review_flag"})
        if milestone_type == "Review Requested":
            return bool(source_types & {"review_flag", "review_comment", "attachment"}) and (
                state.has_milestone_type("Patch Proposed") or "attachment" in source_types or "review_flag" in source_types
            )
        if milestone_type == "Fix Landed":
            return bool(source_types & {"hg_commit", "github_commit"})
        return False

    def _next_gap_id(self) -> str:
        self._gap_counter += 1
        return f"gap{self._gap_counter}"

    def _combine_gathered_information(self, candidate_type: str, gathered: object, recovered: List) -> object:
        return type(gathered)(candidate_type=candidate_type, items=[*gathered.items, *recovered])

    def _build_information_needs(
        self,
        candidate: MilestoneCandidate,
        requirements: List,
        gathered: object,
        recovered: List,
    ) -> List[InformationNeed]:
        information_needs: List[InformationNeed] = []
        for requirement in requirements:
            available_evidence = [
                item
                for item in gathered.items
                if item.source_type in requirement.accepted_source_types
            ]
            recovered_evidence = [
                item
                for item in recovered
                if item.source_type in requirement.accepted_source_types
            ]

            if available_evidence:
                status = "available"
                evidence = available_evidence
            elif recovered_evidence:
                status = "recoverable"
                evidence = recovered_evidence
            else:
                status = "missing_and_needed"
                evidence = []

            information_needs.append(
                InformationNeed(
                    need_id=requirement.requirement_id,
                    description=requirement.description,
                    required_for_milestone=candidate.milestone_type,
                    status=status,
                    source_strategy=requirement.source_strategy,
                    evidence=evidence,
                    creation_action=requirement.creation_action,
                    blocking=requirement.blocking,
                )
            )
        return information_needs

    def _build_information_priority(self, requirements: List) -> List[Dict[str, str]]:
        priorities: List[Dict[str, str]] = []
        seen = set()
        for requirement in requirements:
            key = (requirement.priority_level, requirement.rationale or "")
            if key in seen:
                continue
            seen.add(key)
            priorities.append(
                {
                    "requirement_id": requirement.requirement_id,
                    "priority_level": requirement.priority_level,
                    "confidence": "medium",
                    "rationale": requirement.rationale or "",
                }
            )
        return priorities

    def _signal_trace_summary(self, signals: List[MilestoneSignal]) -> Dict[str, object]:
        technical = [signal.milestone_type for signal in signals if signal.milestone_type in TECHNICAL_MILESTONE_TYPES]
        administrative = [signal.milestone_type for signal in signals if signal.milestone_type in ADMINISTRATIVE_MILESTONE_TYPES]
        return {
            "milestone_count": len(signals),
            "technical_milestones": technical,
            "administrative_milestones": administrative,
            "missing_technical_milestones": len(technical) < 2,
        }

    def _gap_category(self, evaluation: CandidateEvaluation) -> str:
        if any("review" in requirement_id for requirement_id in evaluation.missing_requirement_ids):
            return "missing_review_artifact"
        if any("commit" in requirement_id or "landing" in requirement_id for requirement_id in evaluation.missing_requirement_ids):
            return "missing_commit_linkage"
        if evaluation.candidate.milestone_type in {"Clarification Requested", "Root Cause Hypothesized", "Root Cause Confirmed"}:
            return "ambiguous_comment_evidence"
        return "insufficient_temporal_evidence"

    def _trace_quality_assessment(self, state: TraceStateManager, artifacts: CollectedBugArtifacts) -> TraceQualityAssessment:
        milestones = state.milestones
        transitions = state.transitions
        technical_count = sum(1 for milestone in milestones if milestone.milestone_type in TECHNICAL_MILESTONE_TYPES)
        administrative_count = sum(1 for milestone in milestones if milestone.milestone_type in ADMINISTRATIVE_MILESTONE_TYPES)
        inferred_count = sum(1 for milestone in milestones if milestone.construction_status == "inferred")
        evidence_items = sum(len(milestone.evidence) for milestone in milestones)
        artifact_types = {
            artifact.artifact_type
            for artifact in artifacts.all_artifacts
            if artifact.artifact_type not in {"bug", "history", "comment"}
        }
        completeness_score = min((technical_count + len(transitions)) / 8.0, 1.0)
        artifact_diversity_score = min(len(artifact_types) / 6.0, 1.0)
        evidence_density = evidence_items / max(len(milestones), 1)
        administrative_noise_ratio = administrative_count / max(len(milestones), 1)
        inferred_milestone_ratio = inferred_count / max(len(milestones), 1)

        quality_notes: List[str] = []
        if len(milestones) <= 2 and len(artifacts.all_artifacts) > 10:
            quality_notes.append("Trace is shallow relative to the number of collected artifacts.")
        if len(milestones) < 3:
            quality_notes.append("Trace has fewer than three milestones and is considered shallow.")
        if technical_count == 0:
            quality_notes.append("No technical debugging milestones were established from available artifacts.")
        if administrative_noise_ratio > 0.5:
            quality_notes.append("Administrative milestones dominate the current trace.")
        if artifact_diversity_score < 0.34:
            quality_notes.append("Trace uses a narrow artifact set and may be missing linked technical evidence.")
        if any(gap.category in {"missing_external_artifact", "missing_commit_linkage", "missing_review_artifact"} for gap in state.unresolved_gaps):
            quality_notes.append("Some linked artifacts could not be retrieved and may limit trace completeness.")

        if completeness_score >= 0.75 and administrative_noise_ratio <= 0.35 and inferred_milestone_ratio <= 0.35:
            overall_quality_label = "high"
        elif completeness_score >= 0.45 and administrative_noise_ratio <= 0.6:
            overall_quality_label = "medium"
        else:
            overall_quality_label = "low"

        return TraceQualityAssessment(
            completeness_score=round(completeness_score, 3),
            artifact_diversity_score=round(artifact_diversity_score, 3),
            evidence_density=round(evidence_density, 3),
            administrative_noise_ratio=round(administrative_noise_ratio, 3),
            inferred_milestone_ratio=round(inferred_milestone_ratio, 3),
            overall_quality_label=overall_quality_label,
            quality_notes=quality_notes,
        )

    def _needs_shallow_repair(self, trace: BugResolutionTrace) -> bool:
        milestone_count = len(trace.derived_milestone_trace)
        technical_count = sum(
            1 for milestone in trace.derived_milestone_trace if milestone.milestone_type in TECHNICAL_MILESTONE_TYPES
        )
        admin_count = sum(
            1 for milestone in trace.derived_milestone_trace if milestone.milestone_type in ADMINISTRATIVE_MILESTONE_TYPES
        )
        return milestone_count < 3 or (milestone_count > 0 and admin_count >= technical_count)

    def _is_trace_better(self, candidate: BugResolutionTrace, baseline: BugResolutionTrace) -> bool:
        candidate_technical = sum(
            1 for milestone in candidate.derived_milestone_trace if milestone.milestone_type in TECHNICAL_MILESTONE_TYPES
        )
        baseline_technical = sum(
            1 for milestone in baseline.derived_milestone_trace if milestone.milestone_type in TECHNICAL_MILESTONE_TYPES
        )
        if candidate_technical != baseline_technical:
            return candidate_technical > baseline_technical
        return len(candidate.derived_milestone_trace) > len(baseline.derived_milestone_trace)

    def _build_related_bug_contexts(self, artifacts: CollectedBugArtifacts) -> List[RelatedBugContext]:
        contexts: List[RelatedBugContext] = []
        for related in artifacts.related_bugs:
            contexts.append(
                RelatedBugContext(
                    bug_id=str(related.bug_id),
                    relation_type=related.relation_type,
                    title=related.bug.content.get("summary", ""),
                    status=related.bug.content.get("status", ""),
                    resolution=related.bug.content.get("resolution"),
                    summary=related.bug.content.get("cf_user_story", "") or related.bug.content.get("summary", ""),
                    comments_count=len(related.comments),
                    attachments_count=len(related.attachments),
                    evidence=related.relation_evidence,
                )
            )
        return contexts
