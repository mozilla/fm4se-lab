from __future__ import annotations

from collections import OrderedDict
from typing import List

from .models import Milestone, MilestoneCandidate, MilestoneSignal, parse_timestamp


REPEATABLE_MILESTONE_TYPES = {
    "Clarification Requested",
    "Review Feedback Received",
    "Patch Updated",
    "Fix Backed Out",
    "Fix Relanded",
    "Bug Reopened",
    "CI Failure Detected",
    "CI Fix Applied",
}


class NextMilestoneCandidateGenerator:
    def __init__(self, window_size: int = 6):
        self.window_size = window_size
        self._counter = 0

    def generate(self, current_milestone: Milestone, signals: List[MilestoneSignal]) -> List[MilestoneCandidate]:
        current_ts = parse_timestamp(current_milestone.timestamp)
        unconsumed = [
            signal
            for signal in signals
            if not signal.consumed and parse_timestamp(signal.timestamp) >= current_ts
        ]
        unconsumed.sort(key=lambda s: (parse_timestamp(s.timestamp), s.signal_id))

        if not unconsumed:
            return []

        grouped_signals: "OrderedDict[str, List[MilestoneSignal]]" = OrderedDict()
        for signal in unconsumed:
            if signal.milestone_type == current_milestone.milestone_type:
                continue
            grouped_signals.setdefault(signal.milestone_type, []).append(signal)
            if len(grouped_signals) >= self.window_size:
                break

        candidates: List[MilestoneCandidate] = []
        for milestone_type, candidate_signals in grouped_signals.items():
            if (
                milestone_type not in REPEATABLE_MILESTONE_TYPES
                and any(signal.milestone_type == milestone_type for signal in signals if signal.consumed)
            ):
                continue

            signal = candidate_signals[0]
            same_moment_signals = [
                item
                for item in candidate_signals
                if parse_timestamp(item.timestamp) == parse_timestamp(signal.timestamp)
            ]
            self._counter += 1
            candidates.append(
                MilestoneCandidate(
                    candidate_id=f"cand{self._counter}",
                    milestone_type=milestone_type,
                    timestamp=signal.timestamp,
                    supporting_signals=same_moment_signals,
                )
            )
        return candidates
