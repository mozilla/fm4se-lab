from __future__ import annotations

from typing import Dict, List, Optional

from .diff_utils import get_original_snippets_for_revision


def build_crash_and_patch_context(bug_text: str, patch_diff: str) -> str:
    return (
        "=== CRASH REPORT (Bugzilla) ===\n"
        f"{bug_text}\n\n"
        "=== PATCH DIFF (Phabricator) ===\n"
        f"{patch_diff}\n"
    )


def build_crash_add_and_patch_context(bug_text: str, add_info: str, patch_diff: str) -> str:
    return (
        "=== CRASH REPORT ===\n"
        f"{bug_text}\n"
        "=== ADDITIONAL CRASH INFORMATION ===\n"
        f"{add_info}\n\n"
        "=== PATCH DIFF (Phabricator) ===\n"
        f"{patch_diff}\n"
    )

def build_crash_add_context(bug_text: str, add_info: str) -> str:
    return (
        "=== CRASH REPORT ===\n"
        f"{bug_text}\n"
        "=== ADDITIONAL CRASH INFORMATION ===\n"
        f"{add_info}\n"
    )


def build_bug_and_code_context(
    bug_text: str,
    original_snippets: Dict[str, str],
    additional_info: Optional[str] = None,
    max_files: int = 8,
    max_chars_per_file: int = 4000,
) -> str:
    parts: List[str] = []
    parts.append("=== CRASH REPORT (Bugzilla-like) ===")
    parts.append(bug_text)
    parts.append("")
    if additional_info:
        parts.append("=== ADDITIONAL CRASH INFORMATION ===")
        parts.append(additional_info)
        parts.append("")
    parts.append("=== ORIGINAL CODE CONTEXT (pre-patch, from diff) ===")

    for idx, (path, code) in enumerate(sorted(original_snippets.items())):
        if idx >= max_files:
            parts.append(f"[... {len(original_snippets) - max_files} additional files omitted ...]")
            break
        if max_chars_per_file is not None and len(code) > max_chars_per_file:
            code = code[:max_chars_per_file] + "\n[... code truncated ...]"
        parts.append(f"----- FILE: {path} -----")
        parts.append(code)
        parts.append("")

    return "\n".join(parts)


def build_bug_and_code_context_from_revision(
    bug_text: str,
    revision_id: int,
    patch_id: Optional[int] = None,
    additional_info: Optional[str] = None,
    max_files: int = 8,
    max_chars_per_file: int = 4000,
) -> str:
    original_snippets = get_original_snippets_for_revision(revision_id, patch_id)
    return build_bug_and_code_context(
        bug_text=bug_text,
        original_snippets=original_snippets,
        additional_info=additional_info,
        max_files=max_files,
        max_chars_per_file=max_chars_per_file,
    )
