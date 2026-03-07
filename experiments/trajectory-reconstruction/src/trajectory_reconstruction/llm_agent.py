from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests


class LLMActionAgent:
    """
    Lightweight planner that emits one next action at a time.

    Falls back to deterministic planning when no API key is configured.
    """

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("MODEL_NAME", "gpt-5-nano")

    def choose_next_action(self, bug_id: int, state: Dict[str, Any], iteration: int) -> Dict[str, Any]:
        if not self.api_key:
            return self._fallback_plan(state, iteration)

        prompt = self._build_prompt(bug_id, state, iteration)
        try:
            response = self._call_openai(prompt)
            parsed = self._extract_json(response)
            if not parsed or "action" not in parsed:
                return self._fallback_plan(state, iteration)
            return parsed
        except Exception:
            return self._fallback_plan(state, iteration)

    def _call_openai(self, prompt: str) -> str:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": "You are a software debugging investigation planner."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = "\n".join(candidate.splitlines()[1:-1]).strip()
        if candidate.startswith("json"):
            candidate = "\n".join(candidate.splitlines()[1:]).strip()
        try:
            return json.loads(candidate)
        except Exception:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except Exception:
                    return None
            return None

    def _build_prompt(self, bug_id: int, state: Dict[str, Any], iteration: int) -> str:
        available_tools = [
            "fetch_bug",
            "fetch_comments",
            "fetch_history",
            "fetch_attachments",
            "extract_signals",
            "discover_links",
            "fetch_phabricator_revision",
            "fetch_phabricator_transactions",
            "fetch_phabricator_diff",
            "fetch_hg_revision",
            "fetch_hg_raw_changeset",
            "finish",
        ]

        compact_state = {
            "iteration": iteration,
            "has_bug": bool(state.get("bug")),
            "comments": len(state.get("comments", [])),
            "attachments": len(state.get("attachments", [])),
            "history_events": len(state.get("history", [])),
            "differential_ids": state.get("differential_ids", [])[:20],
            "hg_refs": state.get("hg_refs", [])[:20],
            "changed_files": state.get("changed_files", [])[:20],
            "search_queries_done": state.get("search_queries_done", [])[:20],
            "phab_revisions_fetched": sorted(list((state.get("phab_revisions") or {}).keys()))[:20],
            "phab_transactions_fetched": sorted(list((state.get("phab_transactions") or {}).keys()))[:20],
            "phab_revision_failures": state.get("phab_revision_failures", {}),
            "phab_diff_failures": state.get("phab_diff_failures", {}),
            "hg_raw_fetched": sorted(list((state.get("hg_raw_changesets") or {}).keys()))[:20],
        }

        return (
            "Plan the NEXT best debugging investigation action for Mozilla bug reconstruction.\n"
            f"Bug ID: {bug_id}\n"
            "Constraints:\n"
            "- Choose exactly one action.\n"
            "- Use evidence-driven progression.\n"
            "- Prefer missing high-value artifacts first (linked revisions/commits/diffs/tests).\n"
            "- If enough evidence is collected for trajectory reconstruction, choose finish.\n\n"
            f"Available tools: {available_tools}\n"
            f"Current state summary: {json.dumps(compact_state)}\n\n"
            "Return ONLY JSON with keys: action, params, rationale, done\n"
            "Example: {\"action\":\"fetch_comments\",\"params\":{},\"rationale\":\"...\",\"done\":false}"
        )

    def _fallback_plan(self, state: Dict[str, Any], iteration: int) -> Dict[str, Any]:
        if not state.get("bug"):
            return {"action": "fetch_bug", "params": {}, "rationale": "Need bug metadata first.", "done": False}
        if not state.get("comments"):
            return {"action": "fetch_comments", "params": {}, "rationale": "Need discussion context.", "done": False}
        if not state.get("attachments"):
            return {"action": "fetch_attachments", "params": {}, "rationale": "Need attached artifacts.", "done": False}
        if not state.get("history"):
            return {"action": "fetch_history", "params": {}, "rationale": "Need chronology.", "done": False}
        if not state.get("signals_extracted"):
            return {"action": "extract_signals", "params": {}, "rationale": "Need technical signals.", "done": False}
        if not state.get("links_discovered"):
            return {"action": "discover_links", "params": {}, "rationale": "Need artifact links.", "done": False}

        diff_ids = state.get("differential_ids", [])
        fetched_phab = set((state.get("phab_revisions") or {}).keys())
        phab_failures = state.get("phab_revision_failures", {})
        for did in diff_ids:
            if did not in fetched_phab and int(phab_failures.get(str(did), 0)) < 2:
                return {
                    "action": "fetch_phabricator_revision",
                    "params": {"revision_id": did},
                    "rationale": "Fetch linked review revision metadata.",
                    "done": False,
                }

        fetched_diffs = set((state.get("phab_diffs") or {}).keys())
        diff_failures = state.get("phab_diff_failures", {})
        for did in diff_ids:
            if did not in fetched_diffs and int(diff_failures.get(str(did), 0)) < 2:
                return {
                    "action": "fetch_phabricator_diff",
                    "params": {"revision_id": did},
                    "rationale": "Fetch raw diff for changed files and code-level evidence.",
                    "done": False,
                }

        fetched_tx = set((state.get("phab_transactions") or {}).keys())
        for did in diff_ids:
            if did in fetched_phab and did not in fetched_tx:
                return {
                    "action": "fetch_phabricator_transactions",
                    "params": {"revision_id": did},
                    "rationale": "Fetch reviewer discussion and revision churn signals.",
                    "done": False,
                }

        hg_refs = state.get("hg_refs", [])
        fetched_hg = set((state.get("hg_commits") or {}).keys())
        for ref in hg_refs:
            key = f"{ref.get('repo')}:{ref.get('rev')}"
            if key not in fetched_hg:
                return {
                    "action": "fetch_hg_revision",
                    "params": {"repo": ref.get("repo"), "rev": ref.get("rev")},
                    "rationale": "Fetch linked landing commit metadata.",
                    "done": False,
                }
        
        fetched_raw = set((state.get("hg_raw_changesets") or {}).keys())
        for ref in hg_refs:
            key = f"{ref.get('repo')}:{ref.get('rev')}"
            if key in fetched_hg and key not in fetched_raw:
                return {
                    "action": "fetch_hg_raw_changeset",
                    "params": {"repo": ref.get("repo"), "rev": ref.get("rev")},
                    "rationale": "Fetch raw changeset text for commit interpretation and message context.",
                    "done": False,
                }

        return {"action": "finish", "params": {}, "rationale": "Sufficient evidence collected.", "done": True}
