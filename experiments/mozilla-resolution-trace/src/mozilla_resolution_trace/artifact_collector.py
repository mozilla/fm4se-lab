from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .bugzilla_client import BugzillaClient
from .models import Artifact, Evidence, Gap, normalize_timestamp
from .mozilla_repo_client import CILogClient, GitHubMirrorClient, MercurialClient


HG_REV_URL_RE = re.compile(r"https://hg\.mozilla\.org/([^\s]+?)/rev/([a-f0-9]{8,40})")
GITHUB_COMMIT_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/commit/([a-f0-9]{7,40})")
REGRESSION_BUG_RE = re.compile(
    r"\b(?:regressed by bug|regression from bug|introduced by bug)\s+(\d+)\b",
    flags=re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s<>\"]+")
DIRECT_CI_LOG_RE = re.compile(
    r"https?://[^\s]+(?:live(?:_backing)?\.log|errorsummary\.log|taskcluster[^/\s]*\.log|\.log|\.txt)(?:\?[^\s]*)?$",
    flags=re.IGNORECASE,
)
CI_LINK_RE = re.compile(
    r"https?://[^\s]*(?:taskcluster|treeherder|firefox-ci-tc|\.taskcluster\.)[^\s]*",
    flags=re.IGNORECASE,
)


@dataclass
class RelatedBugArtifacts:
    bug_id: int
    relation_type: str
    relation_evidence: List[Evidence]
    bug: Artifact
    comments: List[Artifact]
    history: List[Artifact]
    attachments: List[Artifact]


@dataclass
class CollectedBugArtifacts:
    bug_id: int
    bug: Artifact
    comments: List[Artifact]
    history: List[Artifact]
    attachments: List[Artifact]
    review_artifacts: List[Artifact]
    repo_artifacts: List[Artifact]
    ci_artifacts: List[Artifact]
    related_bugs: List[RelatedBugArtifacts]
    retrieval_gaps: List[Gap]

    @property
    def all_artifacts(self) -> List[Artifact]:
        related_artifacts: List[Artifact] = []
        for related in self.related_bugs:
            related_artifacts.extend([related.bug, *related.comments, *related.history, *related.attachments])
        return [
            self.bug,
            *self.comments,
            *self.history,
            *self.attachments,
            *self.review_artifacts,
            *self.repo_artifacts,
            *self.ci_artifacts,
            *related_artifacts,
        ]


class ArtifactCollector:
    def __init__(
        self,
        bugzilla_client: Optional[BugzillaClient] = None,
        mercurial_client: Optional[MercurialClient] = None,
        github_client: Optional[GitHubMirrorClient] = None,
        ci_log_client: Optional[CILogClient] = None,
    ):
        self.bugzilla_client = bugzilla_client or BugzillaClient()
        self.mercurial_client = mercurial_client or MercurialClient()
        self.github_client = github_client or GitHubMirrorClient()
        self.ci_log_client = ci_log_client or CILogClient()

    def collect(self, bug_id: int) -> CollectedBugArtifacts:
        bug = self.bugzilla_client.get_bug(bug_id)
        comments = self.bugzilla_client.get_comments(bug_id)
        history = self.bugzilla_client.get_history(bug_id)
        attachments = self.bugzilla_client.get_attachments(bug_id)
        retrieval_gaps: List[Gap] = []

        bug_artifact = Artifact(
            artifact_type="bug",
            identifier=f"bug:{bug_id}",
            timestamp=normalize_timestamp(bug.get("creation_time")),
            content=bug,
        )

        comment_artifacts = [
            Artifact(
                artifact_type="comment",
                identifier=f"comment:{item.get('id', idx)}",
                timestamp=normalize_timestamp(item.get("time")),
                content=item,
            )
            for idx, item in enumerate(comments)
        ]

        history_artifacts = [
            Artifact(
                artifact_type="history",
                identifier=f"history:{idx}",
                timestamp=normalize_timestamp(item.get("when")),
                content=item,
            )
            for idx, item in enumerate(history)
        ]

        attachment_artifacts = [
            Artifact(
                artifact_type="attachment",
                identifier=f"attachment:{item.get('id', idx)}",
                timestamp=normalize_timestamp(item.get("creation_time") or item.get("last_change_time")),
                content=item,
            )
            for idx, item in enumerate(attachments)
        ]
        review_artifacts = self._collect_review_artifacts(attachment_artifacts, comment_artifacts)

        repo_artifacts, repo_gaps = self._collect_repo_artifacts(comment_artifacts)
        ci_artifacts, ci_gaps = self._collect_ci_artifacts(comment_artifacts)
        retrieval_gaps.extend(repo_gaps)
        retrieval_gaps.extend(ci_gaps)
        related_bugs = self._collect_related_regression_bugs(bug, comment_artifacts)
        return CollectedBugArtifacts(
            bug_id=bug_id,
            bug=bug_artifact,
            comments=comment_artifacts,
            history=history_artifacts,
            attachments=attachment_artifacts,
            review_artifacts=review_artifacts,
            repo_artifacts=repo_artifacts,
            ci_artifacts=ci_artifacts,
            related_bugs=related_bugs,
            retrieval_gaps=retrieval_gaps,
        )

    def _collect_review_artifacts(self, attachments: List[Artifact], comments: List[Artifact]) -> List[Artifact]:
        review_artifacts: List[Artifact] = []

        for attachment in attachments:
            flags = attachment.content.get("flags") or []
            for idx, flag in enumerate(flags):
                name = (flag.get("name") or "").lower()
                status = (flag.get("status") or "").lower()
                requestee = flag.get("requestee")
                if name not in {"review", "feedback"}:
                    continue
                review_artifacts.append(
                    Artifact(
                        artifact_type="review_flag",
                        identifier=f"{attachment.identifier}:review:{idx}",
                        timestamp=attachment.timestamp,
                        content={
                            "attachment_id": attachment.identifier,
                            "name": name,
                            "status": status,
                            "requestee": requestee,
                            "summary": attachment.content.get("summary") or attachment.content.get("description"),
                        },
                    )
                )

        for comment in comments:
            text = comment.content.get("text", "")
            if "r?" in text or "r=" in text or "review" in text.lower():
                review_artifacts.append(
                    Artifact(
                        artifact_type="review_comment",
                        identifier=f"{comment.identifier}:review",
                        timestamp=comment.timestamp,
                        content={"text": text[:1000]},
                    )
                )

        return review_artifacts

    def _collect_repo_artifacts(self, comments: List[Artifact]) -> tuple[List[Artifact], List[Gap]]:
        repo_artifacts: List[Artifact] = []
        retrieval_gaps: List[Gap] = []
        seen: Dict[str, bool] = {}

        for comment in comments:
            text = comment.content.get("text", "")
            for repo_path, revision in HG_REV_URL_RE.findall(text):
                key = f"hg:{repo_path}:{revision}"
                if key in seen:
                    continue
                seen[key] = True
                try:
                    rev_json = self.mercurial_client.get_revision(repo_path, revision)
                    raw_changeset = self.mercurial_client.get_raw_changeset(repo_path, revision)
                except Exception as exc:
                    retrieval_gaps.append(
                        self._gap(
                            category="missing_commit_linkage",
                            related_candidate_type="Fix Landed",
                            description=f"Failed to retrieve Mercurial revision {revision} from {repo_path}.",
                            recoverable=True,
                            evidence=[self._comment_evidence(comment, str(exc))],
                        )
                    )
                    continue
                payload = {
                    "repo_path": repo_path,
                    "revision": revision,
                    "revision_json": rev_json,
                    "raw_changeset": raw_changeset,
                }
                repo_artifacts.append(
                    Artifact(
                        artifact_type="hg_commit",
                        identifier=key,
                        timestamp=normalize_timestamp((rev_json or {}).get("date")),
                        content=payload,
                    )
                )

            for owner, repo, sha in GITHUB_COMMIT_RE.findall(text):
                key = f"github:{owner}/{repo}:{sha}"
                if key in seen:
                    continue
                seen[key] = True
                try:
                    commit_json = self.github_client.get_commit(owner, repo, sha)
                except Exception as exc:
                    retrieval_gaps.append(
                        self._gap(
                            category="missing_commit_linkage",
                            related_candidate_type="Fix Landed",
                            description=f"Failed to retrieve GitHub commit {owner}/{repo}@{sha}.",
                            recoverable=True,
                            evidence=[self._comment_evidence(comment, str(exc))],
                        )
                    )
                    continue
                payload = {
                    "owner": owner,
                    "repo": repo,
                    "sha": sha,
                    "commit": commit_json,
                }
                timestamp = None
                if commit_json:
                    timestamp = normalize_timestamp((
                        commit_json.get("commit", {})
                        .get("author", {})
                        .get("date")
                    ))
                repo_artifacts.append(
                    Artifact(
                        artifact_type="github_commit",
                        identifier=key,
                        timestamp=timestamp,
                        content=payload,
                    )
                )

        return repo_artifacts, retrieval_gaps

    def _collect_ci_artifacts(self, comments: List[Artifact]) -> tuple[List[Artifact], List[Gap]]:
        ci_artifacts: List[Artifact] = []
        retrieval_gaps: List[Gap] = []
        seen: Dict[str, bool] = {}

        for comment in comments:
            text = comment.content.get("text", "")
            for url in URL_RE.findall(text):
                normalized_url = url.rstrip(").,]")
                if normalized_url in seen:
                    continue
                if not (DIRECT_CI_LOG_RE.search(normalized_url) or CI_LINK_RE.search(normalized_url)):
                    continue

                seen[normalized_url] = True
                log_text = None
                if DIRECT_CI_LOG_RE.search(normalized_url):
                    try:
                        log_text = self.ci_log_client.get_log(normalized_url)
                    except Exception as exc:
                        retrieval_gaps.append(
                            self._gap(
                                category="missing_external_artifact",
                                related_candidate_type="CI Failure Detected",
                                description=f"Failed to retrieve CI log {normalized_url}.",
                                recoverable=True,
                                evidence=[self._comment_evidence(comment, str(exc))],
                            )
                        )
                failure_signatures = self._extract_failure_signatures(log_text or "")
                status = self._classify_ci_status(log_text or "", normalized_url)
                snippet = self._best_ci_snippet(log_text or "", failure_signatures)
                artifact_type = "ci_log" if log_text else "ci_link"

                ci_artifacts.append(
                    Artifact(
                        artifact_type=artifact_type,
                        identifier=f"{artifact_type}:{len(ci_artifacts) + 1}",
                        timestamp=comment.timestamp,
                        content={
                            "url": normalized_url,
                            "referenced_by": comment.identifier,
                            "text": log_text,
                            "status": status,
                            "failure_signatures": failure_signatures,
                            "snippet": snippet,
                        },
                    )
                )

                if artifact_type == "ci_link" and "treeherder" in normalized_url.lower():
                    retrieval_gaps.append(
                        self._gap(
                            category="missing_external_artifact",
                            related_candidate_type="CI Failure Detected",
                            description=f"Collected CI link {normalized_url} but did not resolve a direct log artifact.",
                            recoverable=True,
                            evidence=[self._comment_evidence(comment, normalized_url)],
                        )
                    )

        return ci_artifacts, retrieval_gaps

    @staticmethod
    def _extract_failure_signatures(log_text: str) -> List[str]:
        if not log_text:
            return []

        signatures: List[str] = []
        patterns = [
            r"TEST-UNEXPECTED-[^\n]+",
            r"AssertionError:[^\n]*",
            r"Traceback \(most recent call last\):",
            r"(?:ERROR|FAIL|FATAL|EXCEPTION)[^\n]{0,220}",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, log_text, flags=re.IGNORECASE):
                line = match.group(0).strip()
                if line and line not in signatures:
                    signatures.append(line[:280])
                if len(signatures) >= 5:
                    return signatures
        return signatures

    @staticmethod
    def _classify_ci_status(log_text: str, url: str) -> str:
        lower = f"{url}\n{log_text}".lower()
        if any(token in lower for token in ["test-unexpected", " failed", "error:", "exception", "permafail", "busted"]):
            return "failed"
        if any(token in lower for token in ["completed successfully", "all tests passed", "green", "success"]):
            return "passed"
        return "unknown"

    @staticmethod
    def _best_ci_snippet(log_text: str, failure_signatures: List[str]) -> Optional[str]:
        if failure_signatures:
            return failure_signatures[0]
        if not log_text:
            return None
        for line in log_text.splitlines():
            trimmed = line.strip()
            if trimmed:
                return trimmed[:280]
        return None

    def _collect_related_regression_bugs(self, bug: Dict, comments: List[Artifact]) -> List[RelatedBugArtifacts]:
        linked_bugs = self._extract_regression_links(bug, comments)
        related_bugs: List[RelatedBugArtifacts] = []

        for linked_bug_id, relation_type, evidence in linked_bugs:
            try:
                linked_bug = self.bugzilla_client.get_bug(linked_bug_id)
            except Exception:
                continue

            linked_comments = self.bugzilla_client.get_comments(linked_bug_id)
            linked_history = self.bugzilla_client.get_history(linked_bug_id)
            linked_attachments = self.bugzilla_client.get_attachments(linked_bug_id)

            related_bugs.append(
                RelatedBugArtifacts(
                    bug_id=linked_bug_id,
                    relation_type=relation_type,
                    relation_evidence=evidence,
                    bug=Artifact(
                        artifact_type="related_bug",
                        identifier=f"related_bug:{linked_bug_id}",
                        timestamp=normalize_timestamp(linked_bug.get("creation_time")),
                        content=linked_bug,
                    ),
                    comments=[
                        Artifact(
                            artifact_type="related_comment",
                            identifier=f"related_comment:{linked_bug_id}:{item.get('id', idx)}",
                            timestamp=normalize_timestamp(item.get("time")),
                            content=item,
                        )
                        for idx, item in enumerate(linked_comments)
                    ],
                    history=[
                        Artifact(
                            artifact_type="related_history",
                            identifier=f"related_history:{linked_bug_id}:{idx}",
                            timestamp=normalize_timestamp(item.get("when")),
                            content=item,
                        )
                        for idx, item in enumerate(linked_history)
                    ],
                    attachments=[
                        Artifact(
                            artifact_type="related_attachment",
                            identifier=f"related_attachment:{linked_bug_id}:{item.get('id', idx)}",
                            timestamp=normalize_timestamp(item.get("creation_time") or item.get("last_change_time")),
                            content=item,
                        )
                        for idx, item in enumerate(linked_attachments)
                    ],
                )
            )

        return related_bugs

    @staticmethod
    def _comment_evidence(comment: Artifact, raw: str) -> Evidence:
        return Evidence(
            source_type="comment",
            source_identifier=comment.identifier,
            timestamp=comment.timestamp,
            normalized_summary="Comment references an artifact that could not be fully retrieved.",
            raw_snippet=raw[:280] if raw else None,
            inferred=False,
        )

    @staticmethod
    def _gap(
        category: str,
        related_candidate_type: str,
        description: str,
        recoverable: bool,
        evidence: List[Evidence],
    ) -> Gap:
        return Gap(
            gap_id=f"collector:{category}:{hashlib.sha1(f'{related_candidate_type}:{description}'.encode('utf-8')).hexdigest()[:10]}",
            category=category,
            related_candidate_type=related_candidate_type,
            description=description,
            recoverable=recoverable,
            evidence=evidence,
        )

    def _extract_regression_links(self, bug: Dict, comments: List[Artifact]) -> List[tuple[int, str, List[Evidence]]]:
        linked: Dict[int, tuple[str, List[Evidence]]] = {}

        for regressed_by_bug in bug.get("regressed_by", []) or []:
            bug_id = int(regressed_by_bug)
            linked[bug_id] = (
                "regressed_by_field",
                [
                    Evidence(
                        source_type="bug",
                        source_identifier=f"bug:{bug.get('id')}",
                        timestamp=normalize_timestamp(bug.get("last_change_time") or bug.get("creation_time")),
                        normalized_summary=f"Bug metadata marks this issue as regressed by bug {bug_id}.",
                        raw_snippet=str(bug.get("regressed_by")),
                    )
                ],
            )

        for comment in comments:
            text = comment.content.get("text", "")
            for match in REGRESSION_BUG_RE.finditer(text):
                linked_bug_id = int(match.group(1))
                if linked_bug_id in linked:
                    continue
                linked[linked_bug_id] = (
                    "regression_comment",
                    [
                        Evidence(
                            source_type="comment",
                            source_identifier=comment.identifier,
                            timestamp=comment.timestamp,
                            normalized_summary=f"Comment links this issue to regression bug {linked_bug_id}.",
                            raw_snippet=text[:280],
                        )
                    ],
                )

        return [(bug_id, relation_type, evidence) for bug_id, (relation_type, evidence) in sorted(linked.items())]
