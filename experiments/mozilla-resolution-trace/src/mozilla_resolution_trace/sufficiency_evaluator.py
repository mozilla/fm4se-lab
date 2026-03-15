from __future__ import annotations

from typing import List, Tuple

from .models import GatheredInformation, InformationRequirement, SufficiencyAssessment


class SufficiencyEvaluator:
    def evaluate(
        self,
        candidate_type: str,
        requirements: List[InformationRequirement],
        gathered: GatheredInformation,
    ) -> Tuple[SufficiencyAssessment, List[str]]:
        if not requirements:
            label = "sufficient" if gathered.items else "insufficient"
            rationale = "No explicit requirements defined." if gathered.items else "No requirements and no evidence gathered."
            return SufficiencyAssessment(candidate_type=candidate_type, label=label, rationale=rationale), ([] if gathered.items else ["no_evidence"])

        blocking_requirements = [requirement for requirement in requirements if requirement.blocking]
        missing: List[str] = []
        for requirement in requirements:
            satisfied = any(item.source_type in requirement.accepted_source_types for item in gathered.items)
            if not satisfied:
                missing.append(requirement.requirement_id)

        blocking_missing = [
            requirement.requirement_id
            for requirement in blocking_requirements
            if requirement.requirement_id in missing
        ]

        if not blocking_missing:
            label = "sufficient"
            rationale = "All blocking information requirements are supported by gathered evidence."
        elif len(blocking_missing) < len(blocking_requirements):
            label = "partially sufficient"
            rationale = "Some, but not all, blocking information requirements are supported by gathered evidence."
        else:
            label = "insufficient"
            rationale = "None of the blocking information requirements could be supported with current evidence."

        return SufficiencyAssessment(candidate_type=candidate_type, label=label, rationale=rationale), missing
