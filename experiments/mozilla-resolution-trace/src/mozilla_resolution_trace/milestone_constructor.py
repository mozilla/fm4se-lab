from __future__ import annotations

from typing import List

from .models import Evidence, Milestone, MilestoneCandidate, SufficiencyAssessment


class MilestoneConstructor:
    def __init__(self):
        self._counter = 1

    def construct(
        self,
        candidate: MilestoneCandidate,
        assessment: SufficiencyAssessment,
        evidence: List[Evidence],
    ) -> Milestone:
        self._counter += 1

        inferred_present = any(item.inferred for item in evidence)
        if assessment.label == "sufficient" and not inferred_present:
            status = "observed"
            confidence = "high"
        else:
            status = "inferred"
            confidence = "medium" if assessment.label != "insufficient" else "low"

        return Milestone(
            milestone_id=f"ms{self._counter}",
            milestone_type=candidate.milestone_type,
            timestamp=candidate.timestamp,
            construction_status=status,
            confidence=confidence,
            evidence=evidence,
            notes=assessment.rationale,
        )
