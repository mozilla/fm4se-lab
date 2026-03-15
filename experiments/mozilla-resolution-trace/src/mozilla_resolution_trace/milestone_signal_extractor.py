from __future__ import annotations

import re
from typing import List

from .artifact_collector import CollectedBugArtifacts
from .models import Evidence, MilestoneSignal, parse_timestamp


REVIEW_REQUEST_RE = re.compile(r"(?<![A-Za-z0-9])r\?(?![A-Za-z0-9])|review\?$|request(?:ing)? review", re.IGNORECASE)
REVIEW_FEEDBACK_RE = re.compile(
    r"(?<![A-Za-z0-9])r-(?![A-Za-z0-9])|\bneeds changes\b|\bnit:\b|\bnit\b|\baddress review comments\b",
    re.IGNORECASE,
)
REGRESSION_IDENTIFIED_RE = re.compile(r"\bregression\b|\bregressed by\b|\bregressed in\b", re.IGNORECASE)
REGRESSION_RANGE_RE = re.compile(
    r"\bmozregression\b|\bpushlog\b|\bregression range\b|\brevision range\b|\bfirst bad\b|\blast good\b|\bchangeset range\b",
    re.IGNORECASE,
)


MILESTONE_TYPE_LIBRARY = [
    "Bug Reported",
    "Clarification Requested",
    "Reproduction Attempted",
    "Reproduction Confirmed",
    "Component Reassigned",
    "Regression Identified",
    "Regression Range Found",
    "Root Cause Hypothesized",
    "Root Cause Confirmed",
    "Patch Proposed",
    "Review Requested",
    "Review Feedback Received",
    "Patch Updated",
    "Test Added",
    "CI Failure Detected",
    "CI Fix Applied",
    "Fix Landed",
    "Fix Backed Out",
    "Fix Relanded",
    "Verification Requested",
    "Bug Resolved",
    "Bug Reopened",
    "Bug Closed",
]


class MilestoneSignalExtractor:
    def __init__(self):
        self._counter = 0

    def extract(self, artifacts: CollectedBugArtifacts) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []

        # Direct bug creation signal.
        bug = artifacts.bug
        signals.append(
            self._signal(
                milestone_type="Bug Reported",
                timestamp=bug.timestamp,
                evidence=[
                    self._evidence(
                        "bug",
                        bug.identifier,
                        bug.timestamp,
                        f"Bug created with status {bug.content.get('status')}.",
                        raw=bug.content.get("summary", ""),
                    )
                ],
                confidence="high",
                observed=True,
            )
        )

        signals.extend(self._from_history(artifacts.history))
        signals.extend(self._from_comments(artifacts.comments))
        signals.extend(self._from_attachments(artifacts.attachments))
        signals.extend(self._from_review_artifacts(artifacts.review_artifacts))
        signals.extend(self._from_repo_artifacts(artifacts.repo_artifacts))
        signals.extend(self._from_ci_artifacts(artifacts.ci_artifacts))
        signals.extend(self._from_related_bugs(artifacts.related_bugs))
        signals.extend(self._from_fix_metadata(artifacts))

        signals.sort(key=lambda s: (parse_timestamp(s.timestamp), s.signal_id))
        return signals

    def _from_history(self, history_artifacts: List) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []

        for history in history_artifacts:
            when = history.timestamp
            for change in history.content.get("changes", []):
                field = (change.get("field_name") or "").lower()
                added = str(change.get("added") or "")
                removed = str(change.get("removed") or "")

                if field == "component" and added and removed and added != removed:
                    signals.append(
                        self._signal(
                            "Component Reassigned",
                            when,
                            [
                                self._evidence(
                                    "history",
                                    history.identifier,
                                    when,
                                    f"Component changed from {removed} to {added}.",
                                )
                            ],
                            confidence="high",
                        )
                    )

                if field in {"status", "bug_status"}:
                    if added.upper() in {"REOPENED", "UNCONFIRMED"}:
                        signals.append(
                            self._signal(
                                "Bug Reopened",
                                when,
                                [
                                    self._evidence(
                                        "history",
                                        history.identifier,
                                        when,
                                        f"Status changed to {added}.",
                                    )
                                ],
                                confidence="high",
                            )
                        )
                    if added.upper() in {"RESOLVED"}:
                        signals.append(
                            self._signal(
                                "Bug Resolved",
                                when,
                                [
                                    self._evidence(
                                        "history",
                                        history.identifier,
                                        when,
                                        "Status changed to RESOLVED.",
                                    )
                                ],
                                confidence="high",
                            )
                        )
                    if added.upper() in {"VERIFIED", "CLOSED"}:
                        signals.append(
                            self._signal(
                                "Bug Closed",
                                when,
                                [
                                    self._evidence(
                                        "history",
                                        history.identifier,
                                        when,
                                        f"Status changed to {added}.",
                                    )
                                ],
                                confidence="high",
                            )
                        )

                if field == "resolution" and added:
                    signals.append(
                        self._signal(
                            "Bug Resolved",
                            when,
                            [
                                self._evidence(
                                    "history",
                                    history.identifier,
                                    when,
                                    f"Resolution set to {added}.",
                                )
                            ],
                            confidence="high",
                        )
                    )

        return signals

    def _from_related_bugs(self, related_bugs: List) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []

        for related in related_bugs:
            related_bug = related.bug
            related_summary = related_bug.content.get("summary", "")
            related_status = related_bug.content.get("status", "")
            evidence = list(related.relation_evidence)
            evidence.append(
                self._evidence(
                    "related_bug",
                    related_bug.identifier,
                    related_bug.timestamp,
                    f"Collected linked regression bug {related.bug_id} with status {related_status}.",
                    raw=related_summary[:280],
                )
            )
            signals.append(
                self._signal(
                    "Regression Identified",
                    related_bug.timestamp,
                    evidence,
                    confidence="high" if related.relation_type == "regressed_by_field" else "medium",
                )
            )
            if related.relation_type == "regressed_by_field":
                signals.append(
                    self._signal(
                        "Regression Range Found",
                        related_bug.timestamp,
                        evidence,
                        confidence="medium",
                    )
                )

        return signals

    def _from_fix_metadata(self, artifacts: CollectedBugArtifacts) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []
        has_repo_landing = any(artifact.artifact_type in {"hg_commit", "github_commit"} for artifact in artifacts.repo_artifacts)
        has_patch = any(attachment.content.get("is_patch") for attachment in artifacts.attachments)

        if has_repo_landing or not has_patch:
            return signals

        for history in artifacts.history:
            for change in history.content.get("changes", []):
                field = (change.get("field_name") or "").lower()
                added = str(change.get("added") or "").upper()
                if field == "resolution" and added == "FIXED":
                    signals.append(
                        self._signal(
                            "Fix Landed",
                            history.timestamp,
                            [
                                self._evidence(
                                    "history",
                                    history.identifier,
                                    history.timestamp,
                                    "Resolution FIXED with patch attachments suggests a landed fix.",
                                    raw="FIXED",
                                    inferred=True,
                                )
                            ],
                            confidence="medium",
                            observed=False,
                        )
                    )
                    return signals

        return signals

    def _from_comments(self, comment_artifacts: List) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []

        for comment in comment_artifacts:
            text = (comment.content.get("text") or "").strip()
            lower = text.lower()
            if not text:
                continue

            emitted_technical = set()

            if self._looks_like_clarification(lower):
                signals.append(
                    self._signal(
                        "Clarification Requested",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment asks for more reproduction or diagnostic details.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )

            if self._looks_like_reproduction_confirmation(lower):
                signals.append(
                    self._signal(
                        "Reproduction Confirmed",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment indicates issue reproduction.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )
                emitted_technical.add("Reproduction Confirmed")

            if self._looks_like_reproduction_attempt(lower):
                signals.append(
                    self._signal(
                        "Reproduction Attempted",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment shows an explicit reproduction attempt or validation effort.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )
                emitted_technical.add("Reproduction Attempted")

            if self._looks_like_regression_identification(lower):
                signals.append(
                    self._signal(
                        "Regression Identified",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment identifies the issue as a regression.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )
                emitted_technical.add("Regression Identified")

            if self._looks_like_regression_range(lower):
                signals.append(
                    self._signal(
                        "Regression Range Found",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment provides a regression window, mozregression result, or pushlog range.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )
                emitted_technical.add("Regression Range Found")

            if self._looks_like_root_cause_hypothesis(lower) and len(emitted_technical) <= 2:
                signals.append(
                    self._signal(
                        "Root Cause Hypothesized",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment suggests a likely technical cause.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )
                emitted_technical.add("Root Cause Hypothesized")

            if self._looks_like_root_cause_confirmation(lower) and "Root Cause Hypothesized" in emitted_technical:
                signals.append(
                    self._signal(
                        "Root Cause Confirmed",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment confirms technical cause.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )

            if REVIEW_REQUEST_RE.search(text):
                signals.append(
                    self._signal(
                        "Review Requested",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment requests review.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )

            if REVIEW_FEEDBACK_RE.search(text):
                signals.append(
                    self._signal(
                        "Review Feedback Received",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment contains review feedback.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )

            if self._looks_like_ci_failure(lower):
                signals.append(
                    self._signal(
                        "CI Failure Detected",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment reports a CI, try, or automation failure.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )

            if self._looks_like_ci_fix(lower):
                signals.append(
                    self._signal(
                        "CI Fix Applied",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment indicates a follow-up change to address CI or try failures.",
                                raw=text[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )

            if "verify" in lower and "request" in lower:
                signals.append(
                    self._signal(
                        "Verification Requested",
                        comment.timestamp,
                        [
                            self._evidence(
                                "comment",
                                comment.identifier,
                                comment.timestamp,
                                "Comment requests verification.",
                                raw=text[:280],
                            )
                        ],
                        confidence="low",
                    )
                )

        return signals

    def _from_attachments(self, attachment_artifacts: List) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []
        patch_attachments = [a for a in attachment_artifacts if a.content.get("is_patch")]

        for attachment in patch_attachments:
            desc = (attachment.content.get("summary") or attachment.content.get("description") or "").lower()
            signals.append(
                self._signal(
                    "Patch Proposed",
                    attachment.timestamp,
                    [
                        self._evidence(
                            "attachment",
                            attachment.identifier,
                            attachment.timestamp,
                            "Patch attachment created.",
                            raw=(attachment.content.get("summary") or attachment.content.get("description") or "")[:280],
                        )
                    ],
                    confidence="high",
                )
            )

            if "r?" in desc or "review" in desc:
                signals.append(
                    self._signal(
                        "Review Requested",
                        attachment.timestamp,
                        [
                            self._evidence(
                                "attachment",
                                attachment.identifier,
                                attachment.timestamp,
                                "Patch attachment indicates review request.",
                                raw=(attachment.content.get("summary") or "")[:280],
                            )
                        ],
                        confidence="medium",
                    )
                )

        if len(patch_attachments) >= 2:
            last = patch_attachments[-1]
            signals.append(
                self._signal(
                    "Patch Updated",
                    last.timestamp,
                    [
                        self._evidence(
                            "attachment",
                            last.identifier,
                            last.timestamp,
                            f"Found {len(patch_attachments)} patch attachments indicating revisions.",
                        )
                    ],
                    confidence="high",
                )
            )

        return signals

    def _from_review_artifacts(self, review_artifacts: List) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []

        for artifact in review_artifacts:
            if artifact.artifact_type == "review_flag":
                name = artifact.content.get("name", "")
                status = artifact.content.get("status", "")
                summary = artifact.content.get("summary") or ""
                if status == "?":
                    signals.append(
                        self._signal(
                            "Review Requested",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "review_flag",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    f"{name.title()} requested on patch metadata.",
                                    raw=summary[:280],
                                )
                            ],
                            confidence="high",
                        )
                    )
                if status in {"+", "-"}:
                    signals.append(
                        self._signal(
                            "Review Feedback Received",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "review_flag",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    f"{name.title()} flag updated to {status}.",
                                    raw=summary[:280],
                                )
                            ],
                            confidence="high",
                        )
                    )

            if artifact.artifact_type == "review_comment":
                text = artifact.content.get("text", "")
                if REVIEW_REQUEST_RE.search(text):
                    signals.append(
                        self._signal(
                            "Review Requested",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "review_comment",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "Comment requests review.",
                                    raw=text[:280],
                                )
                            ],
                            confidence="medium",
                        )
                    )
                if REVIEW_FEEDBACK_RE.search(text) or self._looks_like_review_approval(text.lower()):
                    signals.append(
                        self._signal(
                            "Review Feedback Received",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "review_comment",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "Comment contains review decision or feedback.",
                                    raw=text[:280],
                                )
                            ],
                            confidence="medium",
                        )
                    )

        return signals

    def _from_repo_artifacts(self, repo_artifacts: List) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []

        for artifact in repo_artifacts:
            if artifact.artifact_type == "hg_commit":
                revision_json = artifact.content.get("revision_json") or {}
                raw_changeset = (artifact.content.get("raw_changeset") or "")
                desc = (revision_json.get("desc") or "") + "\n" + raw_changeset
                lower = desc.lower()

                signals.append(
                    self._signal(
                        "Fix Landed",
                        artifact.timestamp,
                        [
                            self._evidence(
                                "hg_commit",
                                artifact.identifier,
                                artifact.timestamp,
                                "Mercurial commit linked from bug discussion.",
                                raw=(revision_json.get("desc") or raw_changeset[:280]),
                            )
                        ],
                        confidence="high",
                    )
                )

                if "backed out" in lower or "backout" in lower:
                    signals.append(
                        self._signal(
                            "Fix Backed Out",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "hg_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "Commit message indicates backout.",
                                    raw=(revision_json.get("desc") or raw_changeset[:280]),
                                )
                            ],
                            confidence="high",
                        )
                    )

                if "reland" in lower:
                    signals.append(
                        self._signal(
                            "Fix Relanded",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "hg_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "Commit message indicates relanding.",
                                    raw=(revision_json.get("desc") or raw_changeset[:280]),
                                )
                            ],
                            confidence="high",
                        )
                    )

                if self._looks_like_test_change(raw_changeset):
                    signals.append(
                        self._signal(
                            "Test Added",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "hg_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "Commit changes include test-related files.",
                                    raw=raw_changeset[:280],
                                    inferred=True,
                                )
                            ],
                            confidence="medium",
                            observed=False,
                        )
                    )

                if self._looks_like_ci_failure(lower):
                    signals.append(
                        self._signal(
                            "CI Failure Detected",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "hg_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "Commit metadata references a CI or automation failure.",
                                    raw=(revision_json.get("desc") or raw_changeset[:280]),
                                )
                            ],
                            confidence="medium",
                        )
                    )

                if self._looks_like_ci_fix(lower):
                    signals.append(
                        self._signal(
                            "CI Fix Applied",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "hg_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "Commit metadata indicates a CI or try fix.",
                                    raw=(revision_json.get("desc") or raw_changeset[:280]),
                                )
                            ],
                            confidence="medium",
                        )
                    )

            if artifact.artifact_type == "github_commit":
                commit = artifact.content.get("commit") or {}
                message = ((commit.get("commit") or {}).get("message") or "") if isinstance(commit, dict) else ""
                files = commit.get("files", []) if isinstance(commit, dict) else []
                if files and any(self._is_test_path(item.get("filename", "")) for item in files):
                    signals.append(
                        self._signal(
                            "Test Added",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "github_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "GitHub mirror commit touches test files.",
                                    raw=str([item.get("filename") for item in files[:5]]),
                                    inferred=True,
                                )
                            ],
                            confidence="medium",
                            observed=False,
                        )
                    )

                lower = message.lower()
                if self._looks_like_ci_failure(lower):
                    signals.append(
                        self._signal(
                            "CI Failure Detected",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "github_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "GitHub mirror commit message references CI failure.",
                                    raw=message[:280],
                                )
                            ],
                            confidence="medium",
                        )
                    )

                if self._looks_like_ci_fix(lower):
                    signals.append(
                        self._signal(
                            "CI Fix Applied",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "github_commit",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "GitHub mirror commit message indicates a CI fix.",
                                    raw=message[:280],
                                )
                            ],
                            confidence="medium",
                        )
                    )

        return signals

    def _from_ci_artifacts(self, ci_artifacts: List) -> List[MilestoneSignal]:
        signals: List[MilestoneSignal] = []

        for artifact in ci_artifacts:
            url = artifact.content.get("url", "")
            status = artifact.content.get("status", "unknown")
            failure_signatures = artifact.content.get("failure_signatures", [])
            snippet = artifact.content.get("snippet") or url
            text = (artifact.content.get("text") or "").lower()

            if status == "failed" or failure_signatures:
                summary = "CI log captured a concrete failure signal."
                if failure_signatures:
                    summary = f"CI log captured failure: {failure_signatures[0][:120]}"
                signals.append(
                    self._signal(
                        "CI Failure Detected",
                        artifact.timestamp,
                        [
                            self._evidence(
                                "ci_log",
                                artifact.identifier,
                                artifact.timestamp,
                                summary,
                                raw=snippet[:280],
                            )
                        ],
                        confidence="high" if artifact.artifact_type == "ci_log" else "medium",
                    )
                )

                if any(token in text for token in ["traceback", "assertionerror", "test-unexpected", "nullpointer", "typeerror", "referenceerror"]):
                    signals.append(
                        self._signal(
                            "Root Cause Hypothesized",
                            artifact.timestamp,
                            [
                                self._evidence(
                                    "ci_log",
                                    artifact.identifier,
                                    artifact.timestamp,
                                    "CI log exposes a concrete failure signature that can guide root-cause analysis.",
                                    raw=snippet[:280],
                                )
                            ],
                            confidence="medium",
                        )
                    )

        return signals

    def _looks_like_test_change(self, raw_changeset: str) -> bool:
        files = re.findall(r"^diff --git a/(.+?) b/(.+?)$", raw_changeset, flags=re.MULTILINE)
        return any(self._is_test_path(a) or self._is_test_path(b) for a, b in files)

    @staticmethod
    def _is_test_path(path: str) -> bool:
        lower = path.lower()
        return "test" in lower or lower.endswith(".ini")

    @staticmethod
    def _looks_like_clarification(lower: str) -> bool:
        return any(
            token in lower
            for token in [
                "needinfo",
                "can you provide",
                "steps to reproduce",
                "str:",
                "please attach",
            ]
        )

    @staticmethod
    def _looks_like_reproduction_confirmation(lower: str) -> bool:
        return any(token in lower for token in ["i can reproduce", "reproduced", "reproducible", "able to repro"])

    @staticmethod
    def _looks_like_reproduction_attempt(lower: str) -> bool:
        return any(
            token in lower
            for token in [
                "tried to reproduce",
                "trying to reproduce",
                "attempted to reproduce",
                "attempting to reproduce",
                "cannot reproduce yet",
                "looking into repro",
            ]
        )

    @staticmethod
    def _looks_like_regression_identification(lower: str) -> bool:
        return bool(REGRESSION_IDENTIFIED_RE.search(lower))

    @staticmethod
    def _looks_like_regression_range(lower: str) -> bool:
        return bool(REGRESSION_RANGE_RE.search(lower))

    @staticmethod
    def _looks_like_root_cause_hypothesis(lower: str) -> bool:
        strong_patterns = [
            "caused by",
            "might be in",
            "suspect",
            "due to",
            "because",
            "regressed in",
            "coming from",
        ]
        technical_terms = [
            "pref",
            "permission",
            "race",
            "null",
            "init",
            "initializ",
            "download",
            "process",
            "ipc",
            "crash",
            "sandbox",
            "file",
            "network",
            "cookie",
            "storage",
            "parental controls",
            "policy",
        ]
        return any(pattern in lower for pattern in strong_patterns) and any(term in lower for term in technical_terms)

    @staticmethod
    def _looks_like_root_cause_confirmation(lower: str) -> bool:
        confirmation_patterns = ["root cause", "turns out", "fixed by", "confirmed to be", "caused by"]
        technical_terms = [
            "pref",
            "permission",
            "race",
            "null",
            "init",
            "initializ",
            "download",
            "process",
            "ipc",
            "crash",
            "sandbox",
            "file",
            "network",
            "cookie",
            "storage",
            "parental controls",
            "policy",
        ]
        return any(pattern in lower for pattern in confirmation_patterns) and any(term in lower for term in technical_terms)

    @staticmethod
    def _looks_like_review_approval(lower: str) -> bool:
        return any(token in lower for token in ["r+", "approved", "looks good", "ship it"])

    @staticmethod
    def _looks_like_ci_failure(lower: str) -> bool:
        return any(
            token in lower
            for token in [
                "try is orange",
                "ci failed",
                "automation failure",
                "test failed on try",
                "backed out for failures",
                "permafail",
                "busted",
            ]
        )

    @staticmethod
    def _looks_like_ci_fix(lower: str) -> bool:
        return any(
            token in lower
            for token in [
                "fixed try",
                "fix try",
                "address ci failure",
                "follow-up for orange",
                "green try",
                "fix lint failure",
            ]
        )

    def _signal(
        self,
        milestone_type: str,
        timestamp: str,
        evidence: List[Evidence],
        confidence: str,
        observed: bool = True,
    ) -> MilestoneSignal:
        self._counter += 1
        return MilestoneSignal(
            signal_id=f"sig{self._counter}",
            milestone_type=milestone_type,
            timestamp=timestamp,
            evidence=evidence,
            confidence=confidence,
            observed=observed,
        )

    @staticmethod
    def _evidence(
        source_type: str,
        source_identifier: str,
        timestamp: str,
        summary: str,
        raw: str = None,
        inferred: bool = False,
    ) -> Evidence:
        return Evidence(
            source_type=source_type,
            source_identifier=source_identifier,
            timestamp=timestamp,
            normalized_summary=summary,
            raw_snippet=raw,
            inferred=inferred,
        )
