from __future__ import annotations

from typing import List

from .models import GatheredInformation, MilestoneCandidate, MilestoneSignal, parse_timestamp


class InformationGatherer:
    def gather(self, candidate: MilestoneCandidate, all_signals: List[MilestoneSignal]) -> GatheredInformation:
        items = []
        for signal in candidate.supporting_signals:
            items.extend(signal.evidence)

        if not items:
            candidate_ts = parse_timestamp(candidate.timestamp)
            for signal in all_signals:
                if signal.milestone_type != candidate.milestone_type:
                    continue
                if parse_timestamp(signal.timestamp) != candidate_ts:
                    continue
                items.extend(signal.evidence)

        return GatheredInformation(candidate_type=candidate.milestone_type, items=items)
