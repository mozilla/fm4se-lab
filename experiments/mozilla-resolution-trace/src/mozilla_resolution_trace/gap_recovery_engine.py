from __future__ import annotations

from typing import List, Tuple

from .artifact_collector import CollectedBugArtifacts
from .models import Evidence, Inference, MilestoneCandidate


class GapRecoveryEngine:
    def __init__(self):
        self._counter = 0

    def recover(
        self,
        candidate: MilestoneCandidate,
        missing_requirement_ids: List[str],
        artifacts: CollectedBugArtifacts,
    ) -> Tuple[List[Evidence], List[Inference]]:
        recovered: List[Evidence] = []
        inferences: List[Inference] = []

        if not missing_requirement_ids:
            return recovered, inferences

        if candidate.milestone_type == "Fix Landed":
            # Conservative recovery: resolved FIXED plus patch evidence can suggest a landed fix.
            has_fixed_resolution = any(
                any(
                    (c.get("field_name") or "").lower() == "resolution" and str(c.get("added") or "").upper() == "FIXED"
                    for c in history.content.get("changes", [])
                )
                for history in artifacts.history
            )
            has_patch = any(att.content.get("is_patch") for att in artifacts.attachments)
            if has_fixed_resolution and has_patch:
                ev = Evidence(
                    source_type="history",
                    source_identifier=artifacts.history[-1].identifier if artifacts.history else artifacts.bug.identifier,
                    timestamp=artifacts.history[-1].timestamp if artifacts.history else artifacts.bug.timestamp,
                    normalized_summary="Resolution is FIXED and patch attachments exist, implying fix likely landed.",
                    inferred=True,
                )
                recovered.append(ev)
                inferences.append(
                    self._inference(
                        "Fix likely landed before resolution based on FIXED status plus patch evidence.",
                        [ev],
                    )
                )

        if candidate.milestone_type == "Test Added":
            for attachment in artifacts.attachments:
                summary = (attachment.content.get("summary") or "").lower()
                if "test" in summary:
                    ev = Evidence(
                        source_type="attachment",
                        source_identifier=attachment.identifier,
                        timestamp=attachment.timestamp,
                        normalized_summary="Patch attachment summary references tests.",
                        raw_snippet=attachment.content.get("summary"),
                        inferred=True,
                    )
                    recovered.append(ev)
                    inferences.append(self._inference("Test-related update inferred from patch summary.", [ev]))
                    break

        if candidate.milestone_type == "Patch Updated":
            patches = [att for att in artifacts.attachments if att.content.get("is_patch")]
            if len(patches) > 1:
                latest = patches[-1]
                ev = Evidence(
                    source_type="attachment",
                    source_identifier=latest.identifier,
                    timestamp=latest.timestamp,
                    normalized_summary=f"Detected {len(patches)} patch attachments, indicating revision cycle.",
                    inferred=True,
                )
                recovered.append(ev)
                inferences.append(self._inference("Patch revision inferred from multiple patch versions.", [ev]))

        return recovered, inferences

    def _inference(self, statement: str, evidence: List[Evidence], confidence: str = "medium") -> Inference:
        self._counter += 1
        return Inference(
            inference_id=f"inf{self._counter}",
            statement=statement,
            confidence=confidence,
            evidence=evidence,
        )
