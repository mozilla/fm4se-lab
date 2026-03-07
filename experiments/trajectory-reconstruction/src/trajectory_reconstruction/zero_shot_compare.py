from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .clients import BugzillaClient, MercurialClient
from .extract import extract_hg_revisions, safe_text
from .reconstructor import MozillaTrajectoryReconstructor


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class RunLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._buffer: List[str] = []

    def log(self, msg: str) -> None:
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        self._buffer.append(line)
        print(line)

    def flush(self) -> None:
        self.log_path.write_text("\n".join(self._buffer) + "\n", encoding="utf-8")


def strip_fix_links(text: str) -> str:
    out = text or ""
    out = re.sub(r"https?://\S+", "[REDACTED_URL]", out)
    lines = []
    for line in out.splitlines():
        low = line.lower()
        if any(k in low for k in ["differential revision", "autoland", "mozilla-central/rev", "phabricator", "landed", "check-in", "r="]):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def sanitize_bug_context(bug: Dict[str, Any], comments: List[Dict[str, Any]], attachments: List[Dict[str, Any]]) -> Dict[str, Any]:
    clean_comments = []
    for c in comments:
        txt = strip_fix_links(safe_text(c.get("text")) or safe_text(c.get("raw_text")))
        if txt:
            clean_comments.append({
                "author": c.get("creator"),
                "time": c.get("creation_time"),
                "text": txt,
            })

    clean_attachments = []
    for a in attachments:
        desc = strip_fix_links(safe_text(a.get("description")))
        if desc:
            clean_attachments.append({"description": desc, "is_patch": bool(a.get("is_patch"))})

    return {
        "bug_id": bug.get("id"),
        "title": bug.get("summary"),
        "product": bug.get("product"),
        "component": bug.get("component"),
        "severity": bug.get("severity"),
        "priority": bug.get("priority"),
        "status": "[REDACTED_FIX_STATUS]",
        "resolution": "[REDACTED_FIX_STATUS]",
        "description": strip_fix_links(safe_text(bug.get("description"))),
        "comments": clean_comments[:40],
        "attachments": clean_attachments[:15],
    }


def sanitize_trajectory(report: Dict[str, Any]) -> Dict[str, Any]:
    root = report.get("BUG FIX TRAJECTORY RECONSTRUCTION", {})
    traj = root.get("Developer Trajectory Reconstruction", {})
    key_signals = root.get("Key Technical Signals", {})

    clean_steps = {}
    for step_key in [
        "Step 1: Bug report intake",
        "Step 2: Component localization",
        "Step 3: Code investigation",
        "Step 4: Root cause discovery",
    ]:
        val = strip_fix_links(safe_text(traj.get(step_key)))
        if val:
            clean_steps[step_key] = val

    clean_signals = {
        "Files referenced": [strip_fix_links(safe_text(x)) for x in key_signals.get("Files referenced", []) if strip_fix_links(safe_text(x))],
        "Functions referenced": [strip_fix_links(safe_text(x)) for x in key_signals.get("Functions referenced", []) if strip_fix_links(safe_text(x))],
        "Tests referenced": [strip_fix_links(safe_text(x)) for x in key_signals.get("Tests referenced", []) if strip_fix_links(safe_text(x))],
    }

    return {
        "trajectory_steps": clean_steps,
        "technical_signals": clean_signals,
    }


def extract_final_commit_from_bug(bug: Dict[str, Any], comments: List[Dict[str, Any]]) -> Tuple[str, str]:
    texts = [safe_text(bug.get("summary")), safe_text(bug.get("description"))]
    texts.extend(safe_text(c.get("text")) for c in comments)
    refs = []
    for t in texts:
        refs.extend(extract_hg_revisions(t))

    for repo, rev, _ in refs:
        if repo == "mozilla-central":
            return repo, rev
    if refs:
        return refs[-1][0], refs[-1][1]
    raise ValueError("No hg revision links found in bug artifacts.")


def hg_diff_to_unified(commit_json: Dict[str, Any]) -> str:
    blocks = commit_json.get("diff") or []
    lines: List[str] = []
    for block in blocks:
        for item in block.get("lines", []):
            raw = item.get("l")
            if isinstance(raw, str):
                lines.append(raw)
    return "".join(lines)


def parse_unified_diff(diff_text: str) -> Dict[str, Any]:
    files = []
    added = []
    removed = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:].strip())
        elif line.startswith("--- a/"):
            files.append(line[6:].strip())
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])

    uniq_files = []
    for f in files:
        if f and f not in uniq_files and f != "/dev/null":
            uniq_files.append(f)

    return {"files": uniq_files, "added": added, "removed": removed}


def overlap_metrics(pred: List[str], gold: List[str]) -> Dict[str, float]:
    p = set(pred)
    g = set(gold)
    tp = len(p & g)
    prec = tp / len(p) if p else 0.0
    rec = tp / len(g) if g else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4), "overlap": tp}


def extract_diff_from_text(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if len(lines) >= 3:
            t = "\n".join(lines[1:-1]).strip()
    if "diff --git" in t:
        idx = t.find("diff --git")
        return t[idx:].strip() + "\n"
    return t + "\n"


def call_openai_generate_diff(prompt: str, logger: RunLogger) -> str:
    import requests

    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("MODEL_NAME", "gpt-4.1-mini")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing.")

    candidate_models = [model]
    if model != "gpt-4.1-mini":
        candidate_models.append("gpt-4.1-mini")

    last_error = None
    for m in candidate_models:
        logger.log(f"Generating zero-shot fix with model={m}")
        payload: Dict[str, Any] = {
            "model": m,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Mozilla engineer. Produce only a unified diff patch that likely fixes the bug. "
                        "Do not include explanations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        if not m.startswith("gpt-5"):
            payload["temperature"] = 0

        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        if resp.status_code < 400:
            content = resp.json()["choices"][0]["message"]["content"]
            return extract_diff_from_text(content)
        last_error = f"status={resp.status_code} body={resp.text[:500]}"
        logger.log(f"Model {m} failed: {last_error}")

    raise RuntimeError(f"All model attempts failed: {last_error}")


def build_generation_prompt(supplemented_context: Dict[str, Any]) -> str:
    return (
        "You are given a bug report supplemented with complementary debugging trajectory context.\n"
        "The supplement intentionally excludes known fix details.\n"
        "Generate a zero-shot likely fix as unified diff only.\n\n"
        f"Supplemented context JSON:\n{json.dumps(supplemented_context, indent=2)}\n\n"
        "Constraints:\n"
        "- Minimal, plausible fix\n"
        "- Prefer files in provided technical signals\n"
        "- Return only diff (diff --git / --- a/ / +++ b/)\n"
    )


def run_zero_shot_compare(bug_id: int, output_dir: Path, trajectory_path: Path | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    load_env_file(root / ".env")

    bugzilla = BugzillaClient()
    mercurial = MercurialClient()
    reconstructor = MozillaTrajectoryReconstructor()

    out_dir = output_dir / str(bug_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(out_dir / "zero_shot_generation_logs.txt")

    try:
        logger.log(f"Start zero-shot compare run for bug {bug_id}")

        if trajectory_path and trajectory_path.exists():
            logger.log(f"Loading trajectory report: {trajectory_path}")
            report = json.loads(trajectory_path.read_text(encoding="utf-8"))
        else:
            logger.log("Generating trajectory report via reconstructor")
            report = reconstructor.reconstruct(bug_id)

        bug = bugzilla.get_bug(bug_id)
        comments = bugzilla.get_comments(bug_id)
        attachments = bugzilla.get_attachments(bug_id)
        if not bug:
            raise RuntimeError(f"Unable to fetch Bugzilla bug {bug_id}")

        logger.log(f"Fetched bug context: comments={len(comments)} attachments={len(attachments)}")

        redacted_bug = sanitize_bug_context(bug, comments, attachments)
        trajectory_supplement = sanitize_trajectory(report)
        supplemented_context = {
            "original_bug_report_redacted": redacted_bug,
            "trajectory_complement": trajectory_supplement,
        }

        (out_dir / "supplemented_bug_context.json").write_text(json.dumps(supplemented_context, indent=2), encoding="utf-8")
        logger.log("Wrote supplemented bug context (bug + trajectory complement minus fix info)")

        repo, rev = extract_final_commit_from_bug(bug, comments)
        logger.log(f"Resolved actual fix commit candidate: {repo}:{rev}")
        commit_json = mercurial.get_revision(repo, rev)
        if not commit_json:
            raise RuntimeError(f"Failed to fetch hg revision {repo}:{rev}")

        actual_diff = hg_diff_to_unified(commit_json)
        if not actual_diff.strip():
            raise RuntimeError("Actual hg diff is empty")
        (out_dir / "actual_fix.diff").write_text(actual_diff, encoding="utf-8")
        logger.log(f"Wrote actual fix diff ({len(actual_diff.splitlines())} lines)")

        prompt = build_generation_prompt(supplemented_context)
        generated_diff = call_openai_generate_diff(prompt, logger)
        (out_dir / "zeroshot_generated_fix.diff").write_text(generated_diff, encoding="utf-8")
        logger.log(f"Wrote zero-shot generated diff ({len(generated_diff.splitlines())} lines)")

        pred = parse_unified_diff(generated_diff)
        gold = parse_unified_diff(actual_diff)

        files_match = set(pred["files"]) == set(gold["files"])
        file_overlap = overlap_metrics(pred["files"], gold["files"])
        add_overlap = overlap_metrics(pred["added"], gold["added"])
        del_overlap = overlap_metrics(pred["removed"], gold["removed"])
        seq_ratio = round(difflib.SequenceMatcher(a=generated_diff, b=actual_diff).ratio(), 4)

        comparison = {
            "bug_id": bug_id,
            "actual_commit": {"repo": repo, "rev": rev, "desc": commit_json.get("desc")},
            "metrics": {
                "files_exact_match": files_match,
                "file_overlap": file_overlap,
                "added_line_overlap": add_overlap,
                "removed_line_overlap": del_overlap,
                "sequence_similarity_ratio": seq_ratio,
            },
            "zeroshot_summary": {"files": pred["files"], "added_lines": len(pred["added"]), "removed_lines": len(pred["removed"])},
            "actual_summary": {"files": gold["files"], "added_lines": len(gold["added"]), "removed_lines": len(gold["removed"])},
        }

        (out_dir / "zeroshot_vs_actual_comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
        logger.log(
            "Zero-shot similarity summary: "
            f"files_exact={files_match}, file_f1={file_overlap['f1']}, add_f1={add_overlap['f1']}, "
            f"del_f1={del_overlap['f1']}, seq={seq_ratio}"
        )
        logger.log("Zero-shot compare run complete")
        return 0
    finally:
        logger.flush()
