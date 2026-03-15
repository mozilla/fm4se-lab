from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .models import Gap, Inference, Milestone, MilestoneSignal, Transition


@dataclass
class TraceStateManager:
    milestones: List[Milestone] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)
    unresolved_gaps: List[Gap] = field(default_factory=list)
    inferred_information: List[Inference] = field(default_factory=list)

    def current_milestone(self) -> Milestone:
        return self.milestones[-1]

    def has_milestone_type(self, milestone_type: str) -> bool:
        return any(milestone.milestone_type == milestone_type for milestone in self.milestones)

    def recent_milestone_types(self, count: int = 3) -> List[str]:
        return [milestone.milestone_type for milestone in self.milestones[-count:]]

    def add_milestone(self, milestone: Milestone) -> None:
        self.milestones.append(milestone)

    def add_transition(self, transition: Transition) -> None:
        self.transitions.append(transition)

    def add_unresolved_gaps(self, gaps: List[Gap]) -> None:
        self.unresolved_gaps.extend(gaps)

    def add_inferences(self, inferences: List[Inference]) -> None:
        self.inferred_information.extend(inferences)

    def consume_signals(self, selected_signals: List[MilestoneSignal]) -> None:
        for signal in selected_signals:
            signal.consumed = True
