from __future__ import annotations

from typing import Dict, Optional, List, Any

import requests

from .config import BUGZILLA_BASE


def _is_meaningful(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip() in ("", "---", "--"):
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    return True


def fetch_bug(bug_id: int) -> Dict:
    resp = requests.get(
        f"{BUGZILLA_BASE}/bug/{bug_id}",
        params={"include_fields": "_all"},
        timeout=30,
    )
    resp.raise_for_status()
    bug = resp.json()["bugs"][0]
    return bug


def fetch_bug_comments(bug_id: int) -> List[Dict[str, Any]]:
    resp = requests.get(
        f"{BUGZILLA_BASE}/bug/{bug_id}/comment",
        params={"include_fields": "id,creator,author,creation_time,time,text"},
        timeout=50,
    )
    resp.raise_for_status()
    data = resp.json()

    bug_key = str(bug_id)
    bug_comments_info = data.get("bugs", {}).get(bug_key, {})
    comments = bug_comments_info.get("comments", []) or []
    return comments


def build_bug_text(
    bug: Dict[str, Any],
    comments: Optional[List[Dict[str, Any]]] = None,
    max_description_chars: int = 4000,
    max_comments: int = 50,
    max_comment_chars: int = 800,
) -> str:
    description = bug.get("description") or bug.get("summary", "")
    if max_description_chars is not None and len(description) > max_description_chars:
        description = description[:max_description_chars] + "\n[... description truncated ...]"

    keywords = ", ".join(bug.get("keywords") or [])
    whiteboard = bug.get("whiteboard") or ""

    lines: List[str] = []

    lines.append(f"Bug {bug.get('id', '')}")
    lines.append(f"Product/Component: {bug.get('product', '')} / {bug.get('component', '')}")
    lines.append(f"Version: {bug.get('version', '')}")
    lines.append(f"Platform/OS: {bug.get('platform', '')} / {bug.get('op_sys', '')}")
    lines.append(f"Summary: {bug.get('summary', '')}")
    lines.append(f"Crash Signature: {bug.get('cf_crash_signature', '')}")
    lines.append(f"Priority/Severity: {bug.get('priority', '')} / {bug.get('severity', '')}")
    lines.append(f"Status/Resolution: {bug.get('status', '')} / {bug.get('resolution', '')}")
    lines.append(f"Created: {bug.get('creation_time', '')}")
    lines.append(f"Last change: {bug.get('last_change_time', '')}")
    lines.append(f"Last resolved: {bug.get('cf_last_resolved', '')}")
    lines.append(f"Comment count: {bug.get('comment_count', '')}")
    lines.append(f"Target milestone: {bug.get('target_milestone', '')}")
    lines.append(f"Classification/Type: {bug.get('classification', '')} / {bug.get('type', '')}")
    lines.append(f"Keywords: {keywords}")
    lines.append(f"Whiteboard: {whiteboard}")
    lines.append(f"QA Whiteboard: {bug.get('cf_qa_whiteboard', '')}")
    lines.append("")

    assigned_to = bug.get("assigned_to_detail") or {}
    creator = bug.get("creator_detail") or {}

    if assigned_to or creator:
        lines.append("People:")
        if _is_meaningful(creator.get("real_name")):
            lines.append(f"  Reporter: {creator.get('real_name')} <{creator.get('email')}>")
        elif _is_meaningful(bug.get("creator")):
            lines.append(f"  Reporter: {bug.get('creator')}")
        if _is_meaningful(assigned_to.get("real_name")):
            lines.append(f"  Assignee: {assigned_to.get('real_name')} <{assigned_to.get('email')}>")
        elif _is_meaningful(bug.get("assigned_to")):
            lines.append(f"  Assignee: {bug.get('assigned_to')}")
        lines.append("")

    regressed_by = bug.get("regressed_by") or []
    regressions = bug.get("regressions") or []
    duplicates = bug.get("duplicates") or []
    depends_on = bug.get("depends_on") or []
    blocks = bug.get("blocks") or []
    see_also = bug.get("see_also") or []

    if any([regressed_by, regressions, duplicates, depends_on, blocks, see_also]):
        lines.append("Relations:")
        if _is_meaningful(regressed_by):
            lines.append(f"  Regressed by: {', '.join(map(str, regressed_by))}")
        if _is_meaningful(regressions):
            lines.append(f"  Regres sions: {', '.join(map(str, regressions))}")
        if _is_meaningful(duplicates):
            lines.append(f"  Duplicates: {', '.join(map(str, duplicates))}")
        if _is_meaningful(depends_on):
            lines.append(f"  Depends on: {', '.join(map(str, depends_on))}")
        if _is_meaningful(blocks):
            lines.append(f"  Blocks: {', '.join(map(str, blocks))}")
        if _is_meaningful(see_also):
            lines.append(f"  See also: {', '.join(see_also)}")
        lines.append("")

    tracking_keys = [
        "cf_tracking_firefox144",
        "cf_tracking_firefox145",
        "cf_tracking_firefox146",
        "cf_tracking_firefox147",
        "cf_tracking_firefox_esr115",
        "cf_tracking_firefox_esr140",
        "cf_tracking_firefox_relnote",
        "cf_tracking_thunderbird_esr115",
        "cf_tracking_thunderbird_esr140",
    ]
    status_keys = [
        "cf_status_firefox144",
        "cf_status_firefox145",
        "cf_status_firefox146",
        "cf_status_firefox147",
        "cf_status_firefox_esr115",
        "cf_status_firefox_esr140",
        "cf_status_thunderbird_esr115",
        "cf_status_thunderbird_esr140",
    ]

    tracking_lines: List[str] = []
    for key in tracking_keys:
        val = bug.get(key)
        if _is_meaningful(val):
            tracking_lines.append(f"  {key}: {val}")

    status_lines: List[str] = []
    for key in status_keys:
        val = bug.get(key)
        if _is_meaningful(val):
            status_lines.append(f"  {key}: {val}")

    if tracking_lines or status_lines:
        lines.append("Tracking / status by release:")
        lines.extend(tracking_lines)
        lines.extend(status_lines)
        lines.append("")

    extra_keys = [
        "cf_performance_impact",
        "cf_accessibility_severity",
        "cf_size_estimate",
        "cf_fx_points",
        "cf_fx_iteration",
        "cf_has_str",
        "cf_webcompat_score",
        "cf_webcompat_priority",
        "cf_user_story",
        "cf_cab_review",
        "cf_a11y_review_project_flag",
        "cf_rank",
        "cf_qa_whiteboard",
    ]
    extra_lines: List[str] = []
    for key in extra_keys:
        val = bug.get(key)
        if _is_meaningful(val):
            extra_lines.append(f"  {key}: {val}")

    if extra_lines:
        lines.append("Additional project metadata:")
        lines.extend(extra_lines)
        lines.append("")

    lines.append("Description:")
    lines.append(description)
    lines.append("")

    if comments:
        lines.append("Comments (Bugzilla):")
        for idx, c in enumerate(comments[:max_comments], start=1):
            author = (
                c.get("author")
                or c.get("creator")
                or c.get("creator_name")
                or "unknown"
            )
            time = c.get("creation_time") or c.get("time") or ""
            text = c.get("text") or ""
            if max_comment_chars is not None and len(text) > max_comment_chars:
                text = text[:max_comment_chars] + "\n[... comment truncated ...]"

            lines.append(f"--- Comment #{idx} ---")
            lines.append(f"Author: {author}")
            if time:
                lines.append(f"Time: {time}")
            lines.append("Text:")
            lines.append(text)
            lines.append("")
        if len(comments) > max_comments:
            lines.append(
                f"[... {len(comments) - max_comments} additional comments omitted ...]"
            )
            lines.append("")

    return "\n".join(lines)
