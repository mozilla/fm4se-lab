from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error, request

from .artifact_collector import CollectedBugArtifacts
from .milestone_signal_extractor import MILESTONE_TYPE_LIBRARY
from .models import Artifact, Evidence, InformationRequirement, MilestoneSignal, parse_timestamp
from .prompt_templates import (
    SYSTEM_CONSTRAINTS,
    cross_artifact_synthesis_prompt,
    information_priority_prompt,
    milestone_disambiguation_prompt,
    shallow_trace_repair_prompt,
)
import dotenv
dotenv.load_dotenv()

LOGGER = logging.getLogger(__name__)

DISAMBIGUATION_MILESTONES = {
    "Reproduction Attempted",
    "Reproduction Confirmed",
    "Regression Identified",
    "Regression Range Found",
    "Root Cause Hypothesized",
    "Root Cause Confirmed",
    "Patch Proposed",
    "Review Feedback Received",
    "Test Added",
    "Fix Landed",
    "Fix Backed Out",
}

SYNTHESIS_MILESTONES = {
    "Patch Proposed",
    "Review Feedback Received",
    "Fix Landed",
    "Root Cause Confirmed",
}

PRIORITY_LEVELS = {"critical", "important", "contextual"}
VERDICTS = {"supported", "weakly_supported", "not_supported"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}


@dataclass
class LLMVerdict:
    candidate_milestone: str
    verdict: str
    confidence: str
    evidence_indices: List[int]
    rationale: str


@dataclass
class PriorityVerdict:
    requirement_id: str
    priority_level: str
    confidence: str
    rationale: str


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: int = 45,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout_seconds = timeout_seconds

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for LLM-assisted refinement.")

        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:  # pragma: no cover
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LLM did not return valid JSON.") from exc


class LLMTraceRefiner:
    def __init__(self, client):
        self.client = client
        self._counter = 0

    def adjudicate_signals(
        self,
        artifacts: CollectedBugArtifacts,
        existing_signals: List[MilestoneSignal],
        repair_mode: bool = False,
        trace_summary: Optional[dict] = None,
    ) -> List[MilestoneSignal]:
        triggers = self._trigger_reasons(artifacts, existing_signals, repair_mode=repair_mode, trace_summary=trace_summary)
        if not triggers:
            return existing_signals

        LOGGER.info("LLM trigger reasons: %s", ", ".join(triggers))
        artifact_index = self._artifact_index(artifacts)
        signals = list(existing_signals)
        signals = self._apply_disambiguation(signals, artifact_index)
        signals.extend(self._apply_synthesis(artifacts, signals, repair_mode=repair_mode, trace_summary=trace_summary))
        signals.sort(key=lambda s: (parse_timestamp(s.timestamp), s.signal_id))
        return signals

    def label_information_priority(
        self,
        milestone_type: str,
        requirements: List[InformationRequirement],
        transition_evidence: List[Evidence],
        low_confidence: bool = False,
    ) -> Optional[List[Dict[str, str]]]:
        if not self._should_label_priorities(milestone_type, requirements, low_confidence):
            return None

        artifact_payload = [
            {
                "source_type": item.source_type,
                "source_identifier": item.source_identifier,
                "timestamp": item.timestamp,
                "summary": item.normalized_summary,
                "raw_snippet": item.raw_snippet,
            }
            for item in transition_evidence[:6]
        ]
        requirement_payload = [
            {
                "requirement_id": item.requirement_id,
                "description": item.description,
                "priority_level": item.priority_level,
                "rationale": item.rationale,
                "blocking": item.blocking,
            }
            for item in requirements
        ]

        prompt = information_priority_prompt(milestone_type, requirement_payload, artifact_payload)
        LOGGER.info("LLM question asked: information-priority labeling for %s", milestone_type)
        response = self.client.complete_json(SYSTEM_CONSTRAINTS, prompt)
        verdicts = self._parse_priority_verdicts(response)
        validated = self._validate_priority_verdicts(verdicts, requirements)
        if validated is None:
            LOGGER.info("LLM priority verdict rejected by deterministic validation.")
            return None
        LOGGER.info("LLM priority verdict accepted for %s.", milestone_type)
        return validated

    def _trigger_reasons(
        self,
        artifacts: CollectedBugArtifacts,
        signals: List[MilestoneSignal],
        repair_mode: bool,
        trace_summary: Optional[dict],
    ) -> List[str]:
        reasons: List[str] = []
        ambiguous = self._ambiguous_groups(signals)
        if ambiguous:
            reasons.append("single artifact matched multiple milestone detectors")
        if repair_mode:
            reasons.append("trace is shallow")
        if trace_summary and trace_summary.get("missing_technical_milestones") and self._has_linked_artifacts(artifacts):
            reasons.append("linked artifacts exist but deterministic extraction is weak")
        if self._has_ambiguous_root_cause(signals):
            reasons.append("root-cause evidence is uncertain")
        if self._has_ordering_ambiguity(signals):
            reasons.append("milestone ordering is ambiguous")
        return reasons

    def _apply_disambiguation(
        self,
        signals: List[MilestoneSignal],
        artifact_index: Dict[str, Artifact],
    ) -> List[MilestoneSignal]:
        ambiguous_groups = self._ambiguous_groups(signals)
        if not ambiguous_groups:
            return signals

        accepted: List[MilestoneSignal] = []
        rejected_ids = set()
        verdict_map: Dict[Tuple[str, str], LLMVerdict] = {}

        for source_identifier, grouped in ambiguous_groups.items():
            artifact = artifact_index.get(source_identifier)
            if artifact is None:
                continue
            candidate_names = [signal.milestone_type for signal in grouped]
            neighboring = self._neighboring_milestones(signals, artifact.timestamp)
            artifact_payload = self._artifact_payload([artifact])[0]
            prompt = milestone_disambiguation_prompt(artifact_payload, candidate_names, neighboring)
            LOGGER.info("LLM question asked: milestone disambiguation for %s", source_identifier)
            response = self.client.complete_json(SYSTEM_CONSTRAINTS, prompt)
            verdicts = self._parse_milestone_verdicts(response)
            validated = self._validate_milestone_verdicts(verdicts, [artifact], candidate_names)
            if validated is None:
                LOGGER.info("LLM disambiguation verdict rejected by deterministic validation for %s", source_identifier)
                continue
            for verdict in validated:
                verdict_map[(source_identifier, verdict.candidate_milestone)] = verdict
            LOGGER.info("LLM verdict returned for %s: %s", source_identifier, [v.verdict for v in validated])

        for signal in signals:
            source_ids = [item.source_identifier for item in signal.evidence]
            matched = False
            keep = True
            for source_identifier in source_ids:
                verdict = verdict_map.get((source_identifier, signal.milestone_type))
                if verdict is None:
                    continue
                matched = True
                if verdict.verdict == "not_supported":
                    keep = False
                    rejected_ids.add(signal.signal_id)
                    break
                if verdict.verdict == "weakly_supported":
                    for item in signal.evidence:
                        item.inferred = True
                        item.normalized_summary = f"LLM weak support: {verdict.rationale}"
            if keep:
                accepted.append(signal)
            elif matched:
                LOGGER.info("Rejected signal %s after LLM disambiguation.", signal.signal_id)
        return accepted

    def _apply_synthesis(
        self,
        artifacts: CollectedBugArtifacts,
        signals: List[MilestoneSignal],
        repair_mode: bool,
        trace_summary: Optional[dict],
    ) -> List[MilestoneSignal]:
        synthesis_groups = self._synthesis_groups(artifacts, signals, repair_mode=repair_mode)
        if not synthesis_groups:
            return []

        additions: List[MilestoneSignal] = []
        for group, candidates in synthesis_groups:
            prompt = (
                shallow_trace_repair_prompt(
                    trace_summary or self._default_trace_summary(signals),
                    self._artifact_payload(group),
                    candidates,
                )
                if repair_mode
                else cross_artifact_synthesis_prompt(
                    self._artifact_payload(group),
                    candidates,
                    self._neighboring_milestones(signals, group[0].timestamp),
                    repair_mode=repair_mode,
                )
            )
            LOGGER.info("LLM question asked: %s", "shallow-trace repair" if repair_mode else "cross-artifact synthesis")
            response = self.client.complete_json(SYSTEM_CONSTRAINTS, prompt)
            verdicts = self._parse_milestone_verdicts(response)
            validated = self._validate_milestone_verdicts(verdicts, group, candidates)
            if validated is None:
                LOGGER.info("LLM synthesis verdict rejected by deterministic validation.")
                continue
            additions.extend(self._verdicts_to_signals(validated, group, signals))
            LOGGER.info("LLM verdict returned: %s", [v.candidate_milestone for v in validated if v.verdict != "not_supported"])
        return additions

    def _ambiguous_groups(self, signals: List[MilestoneSignal]) -> Dict[str, List[MilestoneSignal]]:
        grouped: Dict[str, List[MilestoneSignal]] = {}
        for signal in signals:
            if signal.milestone_type not in DISAMBIGUATION_MILESTONES:
                continue
            for evidence in signal.evidence:
                grouped.setdefault(evidence.source_identifier, []).append(signal)
        return {
            key: value
            for key, value in grouped.items()
            if len({signal.milestone_type for signal in value}) > 1
        }

    def _has_linked_artifacts(self, artifacts: CollectedBugArtifacts) -> bool:
        return bool(artifacts.attachments or artifacts.review_artifacts or artifacts.repo_artifacts or artifacts.related_bugs)

    def _has_ambiguous_root_cause(self, signals: List[MilestoneSignal]) -> bool:
        root_cause_signals = [signal for signal in signals if signal.milestone_type in {"Root Cause Hypothesized", "Root Cause Confirmed"}]
        return any(signal.confidence != "high" for signal in root_cause_signals)

    def _has_ordering_ambiguity(self, signals: List[MilestoneSignal]) -> bool:
        grouped: Dict[str, List[str]] = {}
        for signal in signals:
            grouped.setdefault(signal.timestamp or "", []).append(signal.milestone_type)
        return any(len(set(types)) >= 3 for types in grouped.values())

    def _synthesis_groups(
        self,
        artifacts: CollectedBugArtifacts,
        signals: List[MilestoneSignal],
        repair_mode: bool,
    ) -> List[Tuple[List[Artifact], List[str]]]:
        groups: List[Tuple[List[Artifact], List[str]]] = []
        existing_types = {signal.milestone_type for signal in signals}

        if artifacts.attachments and artifacts.review_artifacts and "Patch Proposed" not in existing_types:
            groups.append(([*artifacts.attachments[:1], *artifacts.review_artifacts[:1]], ["Patch Proposed"]))
        if artifacts.review_artifacts and artifacts.attachments and "Review Feedback Received" not in existing_types:
            groups.append(([*artifacts.review_artifacts[:1], *artifacts.attachments[:1]], ["Review Feedback Received"]))
        if artifacts.repo_artifacts and "Fix Landed" not in existing_types:
            supporting = [*artifacts.repo_artifacts[:1]]
            if artifacts.comments:
                supporting.append(artifacts.comments[0])
            groups.append((supporting, ["Fix Landed"]))
        if artifacts.comments and artifacts.repo_artifacts and "Root Cause Confirmed" not in existing_types:
            groups.append(([artifacts.comments[0], artifacts.repo_artifacts[0]], ["Root Cause Confirmed"]))

        if repair_mode and artifacts.related_bugs and "Regression Identified" not in existing_types:
            groups.append(([artifacts.related_bugs[0].bug], ["Regression Identified", "Regression Range Found"]))

        return groups

    def _neighboring_milestones(self, signals: List[MilestoneSignal], timestamp: Optional[str]) -> List[str]:
        ordered = sorted(signals, key=lambda signal: (parse_timestamp(signal.timestamp), signal.signal_id))
        current = parse_timestamp(timestamp)
        nearby: List[str] = []
        for signal in ordered:
            delta = abs((parse_timestamp(signal.timestamp) - current).total_seconds())
            if delta <= 172800:
                nearby.append(signal.milestone_type)
            if len(nearby) >= 6:
                break
        return nearby

    def _artifact_index(self, artifacts: CollectedBugArtifacts) -> Dict[str, Artifact]:
        index = {artifact.identifier: artifact for artifact in artifacts.all_artifacts}
        for related in artifacts.related_bugs:
            index[related.bug.identifier] = related.bug
        return index

    def _artifact_payload(self, artifacts: Sequence[Artifact]) -> List[dict]:
        payload: List[dict] = []
        for idx, artifact in enumerate(artifacts):
            payload.append(
                {
                    "index": idx,
                    "source_identifier": artifact.identifier,
                    "artifact_type": artifact.artifact_type,
                    "timestamp": artifact.timestamp,
                    "text": self._artifact_snippet(artifact),
                }
            )
        return payload

    def _parse_milestone_verdicts(self, response: Dict) -> List[LLMVerdict]:
        verdicts: List[LLMVerdict] = []
        for item in response.get("results", []):
            candidate = item.get("candidate_milestone")
            verdict = item.get("verdict")
            confidence = item.get("confidence", "medium")
            evidence_indices = item.get("evidence_indices", [])
            rationale = item.get("rationale")
            if candidate not in DISAMBIGUATION_MILESTONES and candidate not in SYNTHESIS_MILESTONES and candidate not in MILESTONE_TYPE_LIBRARY:
                continue
            if verdict not in VERDICTS or confidence not in CONFIDENCE_LEVELS or not isinstance(evidence_indices, list) or not rationale:
                continue
            verdicts.append(
                LLMVerdict(
                    candidate_milestone=candidate,
                    verdict=verdict,
                    confidence=confidence,
                    evidence_indices=[int(index) for index in evidence_indices if isinstance(index, int)],
                    rationale=rationale,
                )
            )
        return verdicts

    def _parse_priority_verdicts(self, response: Dict) -> List[PriorityVerdict]:
        verdicts: List[PriorityVerdict] = []
        for item in response.get("results", []):
            requirement_id = item.get("requirement_id")
            priority_level = item.get("priority_level")
            confidence = item.get("confidence", "medium")
            rationale = item.get("rationale")
            if not requirement_id or priority_level not in PRIORITY_LEVELS or confidence not in CONFIDENCE_LEVELS or not rationale:
                continue
            verdicts.append(
                PriorityVerdict(
                    requirement_id=requirement_id,
                    priority_level=priority_level,
                    confidence=confidence,
                    rationale=rationale,
                )
            )
        return verdicts

    def _validate_milestone_verdicts(
        self,
        verdicts: List[LLMVerdict],
        artifacts: Sequence[Artifact],
        allowed_candidates: Iterable[str],
    ) -> Optional[List[LLMVerdict]]:
        allowed = set(allowed_candidates)
        if not verdicts:
            return []
        for verdict in verdicts:
            if verdict.candidate_milestone not in allowed:
                return None
            if not verdict.evidence_indices:
                return None
            if any(index < 0 or index >= len(artifacts) for index in verdict.evidence_indices):
                return None
        return verdicts

    def _validate_priority_verdicts(
        self,
        verdicts: List[PriorityVerdict],
        requirements: List[InformationRequirement],
    ) -> Optional[List[Dict[str, str]]]:
        if not verdicts:
            return None
        requirement_ids = {item.requirement_id for item in requirements}
        validated: List[Dict[str, str]] = []
        for verdict in verdicts:
            if verdict.requirement_id not in requirement_ids:
                return None
            validated.append(
                {
                    "requirement_id": verdict.requirement_id,
                    "priority_level": verdict.priority_level,
                    "confidence": verdict.confidence,
                    "rationale": verdict.rationale,
                }
            )
        return validated

    def _verdicts_to_signals(
        self,
        verdicts: List[LLMVerdict],
        artifacts: Sequence[Artifact],
        existing_signals: List[MilestoneSignal],
    ) -> List[MilestoneSignal]:
        existing_pairs = {
            (signal.milestone_type, tuple(sorted(item.source_identifier for item in signal.evidence)))
            for signal in existing_signals
        }
        signals: List[MilestoneSignal] = []
        for verdict in verdicts:
            if verdict.verdict == "not_supported":
                continue
            evidence_items: List[Evidence] = []
            cited_identifiers: List[str] = []
            for index in verdict.evidence_indices:
                artifact = artifacts[index]
                cited_identifiers.append(artifact.identifier)
                evidence_items.append(
                    Evidence(
                        source_type=artifact.artifact_type,
                        source_identifier=artifact.identifier,
                        timestamp=artifact.timestamp,
                        normalized_summary=f"LLM-supported {verdict.verdict}: {verdict.rationale}",
                        raw_snippet=self._artifact_snippet(artifact),
                        inferred=True,
                    )
                )
            key = (verdict.candidate_milestone, tuple(sorted(cited_identifiers)))
            if key in existing_pairs:
                continue
            self._counter += 1
            timestamp = min((artifact.timestamp for artifact in (artifacts[index] for index in verdict.evidence_indices) if artifact.timestamp), default=None)
            signals.append(
                MilestoneSignal(
                    signal_id=f"llm_sig{self._counter}",
                    milestone_type=verdict.candidate_milestone,
                    timestamp=timestamp,
                    evidence=evidence_items,
                    confidence=verdict.confidence,
                    observed=False,
                )
            )
        return signals

    def _default_trace_summary(self, signals: List[MilestoneSignal]) -> dict:
        technical = [signal.milestone_type for signal in signals if signal.milestone_type in DISAMBIGUATION_MILESTONES]
        return {
            "milestone_count": len(signals),
            "technical_milestones": technical,
            "missing_technical_milestones": not bool(technical),
        }

    def _should_label_priorities(
        self,
        milestone_type: str,
        requirements: List[InformationRequirement],
        low_confidence: bool,
    ) -> bool:
        if low_confidence:
            return True
        if milestone_type in {"Root Cause Hypothesized", "Root Cause Confirmed", "Regression Range Found"}:
            return True
        if len(requirements) > 1:
            return True
        return any(not item.rationale for item in requirements)

    @staticmethod
    def _artifact_snippet(artifact: Artifact) -> Optional[str]:
        content = artifact.content
        value = (
            content.get("text")
            or content.get("summary")
            or content.get("description")
            or content.get("snippet")
            or (content.get("revision_json") or {}).get("desc")
            or str(content)
        )
        return str(value)[:280] if value else None
