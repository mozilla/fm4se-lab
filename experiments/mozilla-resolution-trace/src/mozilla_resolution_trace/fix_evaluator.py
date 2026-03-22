from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bugzilla_client import BugzillaClient
from .fix_agent import TraceFixAgent
from .llm_refiner import OpenAICompatibleLLMClient
from .mozilla_repo_client import MercurialClient, SearchfoxClient
from .phabricator_client import PhabricatorClient


DIFFERENTIAL_REVISION_RE = re.compile(r"Differential Revision:\s*https?://[^\s]*/D(\d+)", flags=re.IGNORECASE)
PHABRICATOR_ID_RE = re.compile(r"\bD(\d{3,})\b")
HG_REV_URL_RE = re.compile(r"https://hg\.mozilla\.org/([^\s]+?)/rev/([a-f0-9]{8,40})")
FIX_LEAK_TERMS = (
    "differential revision",
    "fix landed",
    "bug resolved",
    "bug closed",
    "autoland",
    "mozilla-central",
    "landed",
    "check-in",
    "r=",
)


@dataclass
class RunLogger:
    log_path: Path

    def __post_init__(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._buffer: List[str] = []

    def log(self, message: str) -> None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        self._buffer.append(line)
        print(line)

    def flush(self) -> None:
        self.log_path.write_text("\n".join(self._buffer) + "\n", encoding="utf-8")


class FixGenerationClient:
    def __init__(self, model: str):
        self.model = model
        self.client = OpenAICompatibleLLMClient(model=model)

    def generate_diff(self, prompt: str) -> str:
        response = self.client.complete_json(
            "You are a Mozilla engineer. Return JSON with a single key named diff whose value is only a unified diff patch.",
            prompt,
        )
        diff = response.get("diff", "")
        if not isinstance(diff, str) or not diff.strip():
            raise RuntimeError("LLM did not return a diff.")
        return self._extract_diff(diff)

    @staticmethod
    def _extract_diff(text: str) -> str:
        payload = text.strip()
        if payload.startswith("```"):
            lines = payload.splitlines()
            if len(lines) >= 3:
                payload = "\n".join(lines[1:-1]).strip()
        marker = payload.find("diff --git")
        if marker >= 0:
            payload = payload[marker:]
        return payload.rstrip() + "\n"


class FixSimilarityJudge:
    def __init__(self, model: str):
        self.client = OpenAICompatibleLLMClient(model=model)

    def judge(
        self,
        *,
        bug_id: int,
        title: str,
        generated_diff: str,
        actual_diff: str,
    ) -> Dict[str, Any]:
        prompt = json.dumps(
            {
                "task": "judge_fix_similarity",
                "bug_id": bug_id,
                "title": title,
                "rubric": {
                    "goal_alignment": "Does the predicted patch appear to solve the same underlying problem?",
                    "file_alignment": "Do the patches touch the same files or code area?",
                    "change_pattern_alignment": "Do they use similar kinds of edits, such as conditionals, guards, tests, or data-flow changes?",
                    "overall_similarity": "Overall semantic similarity from 0 to 1.",
                },
                "generated_diff": generated_diff,
                "actual_diff": actual_diff,
                "output_schema": {
                    "goal_alignment": "high|medium|low",
                    "file_alignment": "high|medium|low",
                    "change_pattern_alignment": "high|medium|low",
                    "overall_similarity_score": "float 0..1",
                    "verdict": "very_similar|partially_similar|different",
                    "rationale": "brief explanation",
                },
            },
            indent=2,
        )
        return self.client.complete_json(
            "You compare two code patches for semantic similarity. Be strict, concise, and return valid JSON only.",
            prompt,
        )


class BatchFixEvaluator:
    def __init__(
        self,
        *,
        bugzilla_client: Optional[BugzillaClient] = None,
        mercurial_client: Optional[MercurialClient] = None,
        phabricator_client: Optional[PhabricatorClient] = None,
        generation_model: str = "gpt-4o-mini",
        judge_model: str = "gpt-4o-mini",
    ):
        self.bugzilla = bugzilla_client or BugzillaClient()
        self.mercurial = mercurial_client or MercurialClient()
        self.phabricator = phabricator_client or PhabricatorClient()
        self.searchfox = SearchfoxClient()
        self.generator = FixGenerationClient(model=generation_model)
        self.fix_agent = TraceFixAgent(
            model=generation_model,
            mercurial_client=self.mercurial,
            searchfox_client=self.searchfox,
        )
        self.judge = FixSimilarityJudge(model=judge_model)

    def run(
        self,
        *,
        candidate_bug_file: Path,
        trace_dir: Path,
        output_dir: Path,
    ) -> Dict[str, Any]:
        bug_ids = self._load_bug_ids(candidate_bug_file)
        summary_rows: List[Dict[str, Any]] = []

        for bug_id in bug_ids:
            trace_path = trace_dir / f"bug_{bug_id}_trace.json"
            if not trace_path.exists():
                continue
            bug_output_dir = output_dir / str(bug_id)
            bug_output_dir.mkdir(parents=True, exist_ok=True)
            logger = RunLogger(bug_output_dir / "evaluation_logs.txt")
            try:
                logger.log(f"Start evaluation for bug {bug_id}")
                result = self._evaluate_bug(bug_id=bug_id, trace_path=trace_path, output_dir=bug_output_dir, logger=logger)
                summary_rows.append(result)
                logger.log(
                    "Completed evaluation with "
                    f"verdict={result['llm_similarity']['verdict']} "
                    f"and seq={result['metrics']['sequence_similarity_ratio']}"
                )
            except Exception as exc:
                failure = {"bug_id": bug_id, "status": "failed", "error": str(exc)}
                summary_rows.append(failure)
                logger.log(f"Evaluation failed: {exc}")
            finally:
                logger.flush()

        summary = {
            "candidate_bug_file": str(candidate_bug_file),
            "trace_dir": str(trace_dir),
            "evaluated_bug_count": sum(1 for row in summary_rows if row.get("status") == "ok"),
            "results": summary_rows,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "batch_evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def _evaluate_bug(self, *, bug_id: int, trace_path: Path, output_dir: Path, logger: RunLogger) -> Dict[str, Any]:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        bug = self.bugzilla.get_bug(bug_id)
        comments = self.bugzilla.get_comments(bug_id)
        attachments = self.bugzilla.get_attachments(bug_id)

        generation_context = self._build_generation_context(
            bug=bug,
            trace=trace,
        )
        (output_dir / "generation_context.json").write_text(json.dumps(generation_context, indent=2), encoding="utf-8")
        logger.log("Wrote generation context assembled from original bug report plus stored trace")

        actual_fix = self._resolve_actual_fix(bug=bug, comments=comments)
        (output_dir / "actual_fix.diff").write_text(actual_fix["diff"], encoding="utf-8")
        (output_dir / "actual_fix_metadata.json").write_text(json.dumps(actual_fix["metadata"], indent=2), encoding="utf-8")
        logger.log(f"Resolved actual fix via {actual_fix['metadata']['source']}")

        agent_result = self.fix_agent.generate_fix(
            bug=bug,
            comments=comments,
            attachments=attachments,
            trace=trace,
        )
        (output_dir / "generation_plan.json").write_text(json.dumps(agent_result["plan"], indent=2), encoding="utf-8")
        (output_dir / "generation_profile.json").write_text(json.dumps(agent_result["profile"], indent=2), encoding="utf-8")
        (output_dir / "retrieval_signals.json").write_text(json.dumps(agent_result["retrieval_signals"], indent=2), encoding="utf-8")
        (output_dir / "ranked_candidates.json").write_text(json.dumps(agent_result["ranked_candidates"], indent=2), encoding="utf-8")
        (output_dir / "retrieved_context.json").write_text(json.dumps(agent_result["retrieved_context"], indent=2), encoding="utf-8")
        logger.log(
            "Retrieved grounded source context for "
            f"{len(agent_result['retrieved_context'].get('regions', []))} region(s)"
        )
        generated_diff = agent_result["diff"]
        (output_dir / "generated_fix.diff").write_text(generated_diff, encoding="utf-8")
        logger.log(f"Generated agentic candidate diff ({len(generated_diff.splitlines())} lines)")

        pred = self._parse_unified_diff(generated_diff)
        gold = self._parse_unified_diff(actual_fix["diff"])
        metrics = {
            "files_exact_match": set(pred["files"]) == set(gold["files"]),
            "file_overlap": self._overlap_metrics(pred["files"], gold["files"]),
            "added_line_overlap": self._overlap_metrics(pred["added"], gold["added"]),
            "removed_line_overlap": self._overlap_metrics(pred["removed"], gold["removed"]),
            "sequence_similarity_ratio": round(difflib.SequenceMatcher(a=generated_diff, b=actual_fix["diff"]).ratio(), 4),
        }

        llm_similarity = self.judge.judge(
            bug_id=bug_id,
            title=bug.get("summary") or trace.get("title") or f"Bug {bug_id}",
            generated_diff=generated_diff,
            actual_diff=actual_fix["diff"],
        )

        result = {
            "bug_id": bug_id,
            "status": "ok",
            "trace_path": str(trace_path),
            "actual_fix_metadata": actual_fix["metadata"],
            "metrics": metrics,
            "llm_similarity": llm_similarity,
            "generated_summary": {
                "files": pred["files"],
                "added_lines": len(pred["added"]),
                "removed_lines": len(pred["removed"]),
            },
            "actual_summary": {
                "files": gold["files"],
                "added_lines": len(gold["added"]),
                "removed_lines": len(gold["removed"]),
            },
        }
        (output_dir / "evaluation_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    def _build_generation_context(
        self,
        *,
        bug: Dict[str, Any],
        trace: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "original_bug_report": {
                "bug_id": bug.get("id"),
                "title": bug.get("summary"),
                "product": bug.get("product"),
                "component": bug.get("component"),
                "severity": bug.get("severity"),
                "priority": bug.get("priority"),
                "status": bug.get("status"),
                "resolution": bug.get("resolution"),
                "description": self._safe_text(bug.get("description")),
            },
            "resolution_trace": trace,
        }

    def _resolve_actual_fix(self, *, bug: Dict[str, Any], comments: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        repo, rev, commit_json = self._resolve_commit_from_bug(bug, comments)
        commit_desc = self._safe_text((commit_json or {}).get("desc"))
        revision_id = self._extract_revision_id(commit_desc)
        if revision_id is not None:
            phab_diff = self._fetch_phabricator_diff(revision_id)
            if phab_diff:
                return {
                    "diff": phab_diff,
                    "metadata": {
                        "source": "phabricator",
                        "revision_id": revision_id,
                        "repo": repo,
                        "rev": rev,
                        "commit_desc": commit_desc,
                    },
                }

        raw_diff = self._hg_diff_to_unified(commit_json or {})
        if not raw_diff.strip():
            raise RuntimeError(f"Unable to resolve actual diff for bug {bug.get('id')}")
        return {
            "diff": raw_diff,
            "metadata": {
                "source": "hg",
                "revision_id": revision_id,
                "repo": repo,
                "rev": rev,
                "commit_desc": commit_desc,
            },
        }

    def _resolve_commit_from_bug(
        self,
        bug: Dict[str, Any],
        comments: Sequence[Dict[str, Any]],
    ) -> Tuple[str, str, Optional[Dict[str, Any]]]:
        texts = [self._safe_text(bug.get("summary")), self._safe_text(bug.get("description"))]
        texts.extend(self._safe_text(item.get("text")) for item in comments)
        refs: List[Tuple[str, str]] = []
        for text in texts:
            refs.extend((repo, rev) for repo, rev in HG_REV_URL_RE.findall(text))

        preferred = [item for item in refs if item[0] == "mozilla-central"]
        selected = preferred[0] if preferred else (refs[-1] if refs else None)
        if selected is None:
            raise RuntimeError(f"No hg revision links found for bug {bug.get('id')}")

        repo, rev = selected
        commit_json = self.mercurial.get_revision(repo, rev)
        if not commit_json:
            raise RuntimeError(f"Failed to fetch hg revision {repo}:{rev}")
        return repo, rev, commit_json

    def _fetch_phabricator_diff(self, revision_id: int) -> Optional[str]:
        revision = self.phabricator.get_revision_by_id(revision_id)
        if not revision:
            return None
        phid = revision.get("phid")
        if not phid:
            return None
        metadata = self.phabricator.get_diff_metadata(phid)
        diff_ids = [item.get("id") for item in metadata if item.get("id") is not None]
        if not diff_ids:
            return None
        return self.phabricator.get_raw_diff(int(diff_ids[-1]))

    @staticmethod
    def _extract_revision_id(commit_desc: str) -> Optional[int]:
        for pattern in (DIFFERENTIAL_REVISION_RE, PHABRICATOR_ID_RE):
            match = pattern.search(commit_desc or "")
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _hg_diff_to_unified(commit_json: Dict[str, Any]) -> str:
        blocks = commit_json.get("diff") or []
        lines: List[str] = []
        for block in blocks:
            for item in block.get("lines", []):
                raw = item.get("l")
                if isinstance(raw, str):
                    lines.append(raw)
        return "".join(lines)

    @staticmethod
    def _parse_unified_diff(diff_text: str) -> Dict[str, List[str]]:
        files: List[str] = []
        added: List[str] = []
        removed: List[str] = []

        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                files.append(line[6:].strip())
            elif line.startswith("--- a/"):
                files.append(line[6:].strip())
            elif line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])

        unique_files: List[str] = []
        for path in files:
            if path and path != "/dev/null" and path not in unique_files:
                unique_files.append(path)
        return {"files": unique_files, "added": added, "removed": removed}

    @staticmethod
    def _overlap_metrics(predicted: Sequence[str], actual: Sequence[str]) -> Dict[str, float]:
        pred_set = set(predicted)
        actual_set = set(actual)
        overlap = len(pred_set & actual_set)
        precision = overlap / len(pred_set) if pred_set else 0.0
        recall = overlap / len(actual_set) if actual_set else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "overlap": overlap,
        }

    @staticmethod
    def _safe_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _load_bug_ids(candidate_bug_file: Path) -> List[int]:
        bug_ids: List[int] = []
        for raw_line in candidate_bug_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            bug_ids.append(int(line))
        return bug_ids
