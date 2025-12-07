from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .phabricator import fetch_raw_diff

Hunk = Tuple[int, List[str]]


def extract_original_hunks_by_file(raw_diff: str) -> Dict[str, List[Hunk]]:
    lines = raw_diff.splitlines()
    file_path: Optional[str] = None
    results: Dict[str, List[Hunk]] = {}

    hunk_old_start: Optional[int] = None
    hunk_lines: List[str] = []
    in_hunk = False

    hunk_header_re = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    def flush_hunk():
        nonlocal hunk_old_start, hunk_lines, in_hunk, file_path
        if in_hunk and file_path is not None and hunk_old_start is not None:
            results.setdefault(file_path, []).append((hunk_old_start, hunk_lines))
        hunk_old_start = None
        hunk_lines = []
        in_hunk = False

    for line in lines:
        if line.startswith("diff --git "):
            flush_hunk()
            file_path = None

        elif line.startswith("--- "):
            path = line[4:]
            if path.startswith("a/"):
                path = path[2:]
            file_path = path

        elif line.startswith("@@ "):
            flush_hunk()
            m = hunk_header_re.match(line)
            if m:
                hunk_old_start = int(m.group(1))
                in_hunk = True

        elif in_hunk:
            if not line:
                continue
            prefix = line[0]
            content = line[1:]
            if prefix in (" ", "-"):
                hunk_lines.append(content)

    flush_hunk()
    return results


def get_original_snippets_from_diff(raw_diff: str) -> Dict[str, str]:
    hunks_by_file = extract_original_hunks_by_file(raw_diff)

    result: Dict[str, str] = {}
    for path, hunks in hunks_by_file.items():
        all_lines: List[str] = []
        for _, lines in hunks:
            if all_lines:
                all_lines.append("")
            all_lines.extend(lines)
        result[path] = "\n".join(all_lines)

    return result


def get_original_snippets_for_revision(
    revision_id: int,
    patch_id: Optional[int] = None,
) -> Dict[str, str]:
    raw = fetch_raw_diff(revision_id, patch_id)
    return get_original_snippets_from_diff(raw)
