from __future__ import annotations

from typing import Dict, List

from .models import InformationRequirement


REQUIREMENT_LIBRARY: Dict[str, List[InformationRequirement]] = {
    "Clarification Requested": [
        InformationRequirement(
            requirement_id="clarifying_comment",
            description="Comment that asks for missing details or reproduction context.",
            accepted_source_types=["comment"],
            source_strategy="bugzilla_comment",
            priority_level="important",
            rationale="Clarifications reduce ambiguity before debugging can proceed.",
            creation_action="Request the reporter to provide concrete reproduction details or missing diagnostic context.",
        )
    ],
    "Reproduction Attempted": [
        InformationRequirement(
            requirement_id="repro_attempt",
            description="Discussion shows someone attempted to reproduce the issue or validate the report.",
            accepted_source_types=["comment"],
            source_strategy="bugzilla_comment",
            priority_level="critical",
            rationale="Reproduction attempts establish whether the report can be investigated further.",
            creation_action="Attempt reproduction on a matching environment and record what was tried.",
        )
    ],
    "Reproduction Confirmed": [
        InformationRequirement(
            requirement_id="repro_confirmation",
            description="Comment confirms issue can be reproduced.",
            accepted_source_types=["comment"],
            source_strategy="bugzilla_comment",
            priority_level="critical",
            rationale="Confirmed reproduction is core technical evidence that the bug behavior is real and understood.",
            creation_action="Reproduce the bug on a matching Mozilla build and record reliable steps to reproduce.",
        )
    ],
    "Component Reassigned": [
        InformationRequirement(
            requirement_id="component_change",
            description="History shows component changed.",
            accepted_source_types=["history"],
            source_strategy="bug_history",
            priority_level="contextual",
            rationale="Component movement is process context rather than core debugging evidence.",
            blocking=False,
        )
    ],
    "Regression Identified": [
        InformationRequirement(
            requirement_id="regression_signal",
            description="Discussion, history, or linked bug identifies the issue as a regression.",
            accepted_source_types=["comment", "history", "related_bug"],
            source_strategy="discussion_or_related_bug",
            priority_level="important",
            rationale="Regression evidence narrows the search space and often points to likely code changes.",
            creation_action="Determine whether the issue regressed from a previous working state and document that linkage.",
        )
    ],
    "Regression Range Found": [
        InformationRequirement(
            requirement_id="regression_range",
            description="A mozregression result, pushlog, or narrowed range is recorded.",
            accepted_source_types=["comment", "related_bug"],
            source_strategy="regression_analysis",
            priority_level="critical",
            rationale="A concrete regression range is one of the strongest inputs for root-cause analysis.",
            creation_action="Run mozregression or inspect pushlogs to narrow the regression window.",
        )
    ],
    "Root Cause Hypothesized": [
        InformationRequirement(
            requirement_id="diagnosis_hypothesis",
            description="Technical hypothesis appears in comments.",
            accepted_source_types=["comment", "related_bug"],
            source_strategy="bugzilla_comment",
            priority_level="critical",
            rationale="A concrete diagnosis hypothesis marks the shift from reproduction to debugging.",
            creation_action="Inspect the failing code path and document a concrete technical hypothesis for the defect.",
        )
    ],
    "Root Cause Confirmed": [
        InformationRequirement(
            requirement_id="diagnosis_confirmation",
            description="Technical diagnosis confirmed by discussion.",
            accepted_source_types=["comment", "hg_commit", "related_bug"],
            source_strategy="discussion_or_commit",
            priority_level="critical",
            rationale="Confirmed root cause supports implementation confidence and reduces speculative transitions.",
            creation_action="Validate the suspected root cause with code inspection, experiment, or commit evidence.",
        )
    ],
    "Patch Proposed": [
        InformationRequirement(
            requirement_id="patch_attachment",
            description="Patch attachment is available.",
            accepted_source_types=["attachment"],
            source_strategy="bugzilla_attachment",
            priority_level="critical",
            rationale="An implementation artifact is required before review and landing can be traced credibly.",
            creation_action="Write and attach a patch that addresses the identified defect.",
        )
    ],
    "Review Requested": [
        InformationRequirement(
            requirement_id="review_request",
            description="Review request appears in comment or attachment metadata.",
            accepted_source_types=["comment", "attachment", "review_flag", "review_comment"],
            source_strategy="bugzilla_review_metadata",
            priority_level="important",
            rationale="Review request marks the transition from implementation to collaborative validation.",
            creation_action="Request review on the proposed patch or patch series.",
            blocking=False,
        )
    ],
    "Review Feedback Received": [
        InformationRequirement(
            requirement_id="review_feedback",
            description="Reviewer feedback comment is present.",
            accepted_source_types=["comment", "review_flag", "review_comment"],
            source_strategy="bugzilla_comment",
            priority_level="important",
            rationale="Review feedback explains why patches changed and whether they were accepted.",
            creation_action="Obtain reviewer feedback on the proposed fix.",
        )
    ],
    "Patch Updated": [
        InformationRequirement(
            requirement_id="revision_signal",
            description="Multiple patch versions, obsolete patch metadata, or follow-up commit indicates patch updates.",
            accepted_source_types=["attachment", "comment", "review_flag", "review_comment"],
            source_strategy="bugzilla_attachment",
            priority_level="important",
            rationale="Patch updates preserve implementation-review iteration instead of collapsing cycles.",
            creation_action="Revise the patch to address review feedback or test failures.",
        )
    ],
    "Test Added": [
        InformationRequirement(
            requirement_id="test_change",
            description="Diff or commit shows test-related file changes.",
            accepted_source_types=["hg_commit", "github_commit", "attachment"],
            source_strategy="diff_or_commit",
            priority_level="important",
            rationale="Test additions are strong validation evidence but not always required for progress.",
            creation_action="Create a failing or regression test that captures the bug behavior.",
            blocking=False,
        )
    ],
    "CI Failure Detected": [
        InformationRequirement(
            requirement_id="ci_failure",
            description="Try, CI, or automation failure is supported by logs, discussion, or commit metadata.",
            accepted_source_types=["ci_log", "comment", "hg_commit", "github_commit"],
            source_strategy="ci_discussion_or_commit",
            priority_level="important",
            rationale="CI failures can interrupt landing and trigger follow-up implementation cycles.",
            creation_action="Inspect failing CI or try jobs and capture the blocking failure signal.",
        )
    ],
    "CI Fix Applied": [
        InformationRequirement(
            requirement_id="ci_fix",
            description="Follow-up discussion or commit indicates the CI failure was addressed.",
            accepted_source_types=["comment", "attachment", "hg_commit", "github_commit"],
            source_strategy="ci_followup",
            priority_level="important",
            rationale="A CI fix preserves the distinction between code correctness and landing readiness.",
            creation_action="Apply and record the change needed to resolve the CI or try failure.",
        )
    ],
    "Fix Landed": [
        InformationRequirement(
            requirement_id="landing_commit",
            description="Landed commit references the bug or is linked in discussion.",
            accepted_source_types=["hg_commit", "github_commit"],
            source_strategy="repository_history",
            priority_level="critical",
            rationale="Landing evidence is the strongest proof that the implementation reached the repository.",
            creation_action="Land the approved patch and record the resulting commit linkage.",
        )
    ],
    "Fix Backed Out": [
        InformationRequirement(
            requirement_id="backout_commit",
            description="Commit metadata indicates backout.",
            accepted_source_types=["hg_commit", "github_commit"],
            source_strategy="repository_history",
            priority_level="important",
            rationale="Backouts indicate a failed landing cycle and should remain visible in the trace.",
        )
    ],
    "Fix Relanded": [
        InformationRequirement(
            requirement_id="reland_commit",
            description="Commit metadata indicates relanding after backout.",
            accepted_source_types=["hg_commit", "github_commit"],
            source_strategy="repository_history",
            priority_level="important",
            rationale="Relanding closes the loop after a failed landing cycle.",
            creation_action="Reland the fix after correcting the issue that caused the backout.",
        )
    ],
    "Verification Requested": [
        InformationRequirement(
            requirement_id="verification_request",
            description="Comment requests verification or QA validation.",
            accepted_source_types=["comment"],
            source_strategy="bugzilla_comment",
            priority_level="contextual",
            rationale="Verification is process validation after the main technical work is complete.",
            creation_action="Request QA or reporter verification on a build containing the fix.",
            blocking=False,
        )
    ],
    "Bug Resolved": [
        InformationRequirement(
            requirement_id="resolution_status",
            description="History shows resolved status/resolution.",
            accepted_source_types=["history", "bug"],
            source_strategy="bug_history",
            priority_level="contextual",
            rationale="Resolution status is administrative confirmation unless backed by stronger technical evidence.",
            blocking=False,
        )
    ],
    "Bug Reopened": [
        InformationRequirement(
            requirement_id="reopened_status",
            description="History shows bug reopened.",
            accepted_source_types=["history"],
            source_strategy="bug_history",
            priority_level="contextual",
            rationale="Reopenings matter for process history but are not technical evidence by themselves.",
        )
    ],
    "Bug Closed": [
        InformationRequirement(
            requirement_id="closed_status",
            description="History shows bug moved to VERIFIED/CLOSED.",
            accepted_source_types=["history"],
            source_strategy="bug_history",
            priority_level="contextual",
            rationale="Closure is an administrative end-state unless paired with stronger validation evidence.",
            blocking=False,
        )
    ],
}


class TransitionRequirementAnalyzer:
    def requirements_for(self, milestone_type: str) -> List[InformationRequirement]:
        return list(REQUIREMENT_LIBRARY.get(milestone_type, []))
