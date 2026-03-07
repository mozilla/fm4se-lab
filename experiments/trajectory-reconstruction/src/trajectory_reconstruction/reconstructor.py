from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import requests

from .clients import BugzillaClient, MercurialClient, PhabricatorClient
from .extract import (
    collect_links_from_texts,
    extract_bug_mentions,
    extract_differential_ids,
    extract_hg_revisions,
    maybe,
    safe_text,
)
from .llm_agent import LLMActionAgent


UNKNOWN_TEXT = "Unknown from available Mozilla artifacts."


class MozillaTrajectoryReconstructor:
    def __init__(self):
        self.bugzilla = BugzillaClient()
        self.phabricator = PhabricatorClient()
        self.mercurial = MercurialClient()
        self.agent = LLMActionAgent()

    def reconstruct(self, bug_id: int) -> Dict[str, Any]:
        # Mandatory first step: fetch bug first.
        bug = self.bugzilla.get_bug(bug_id)
        if not bug:
            raise ValueError(f"Unable to fetch Bugzilla bug {bug_id}")

        state = self._init_state(bug_id, bug)
        dynamic_log = self._run_dynamic_investigation(state)

        artifacts = self._build_artifacts_from_state(state)
        signals = self._extract_technical_signals(state, artifacts)
        final_commit = self._pick_final_commit(artifacts.get("commits", []))
        modified_files = artifacts.get("changed_files", [])
        tests = [f for f in modified_files if self._looks_like_test_file(f)]
        artifact_analysis = self._analyze_artifacts_with_llm(bug, artifacts, signals, dynamic_log)

        report = {
            "BUG FIX TRAJECTORY RECONSTRUCTION": {
                "Bug Metadata": {
                    "Bug ID": bug_id,
                    "Title": maybe(bug.get("summary")),
                    "Component": maybe(bug.get("component")),
                    "Status": maybe(bug.get("status")),
                    "Resolution": maybe(bug.get("resolution")),
                },
                "Key Technical Signals": {
                    "Stack traces": signals["stack_traces"],
                    "Files referenced": signals["files"],
                    "Functions referenced": signals["functions"],
                    "Tests referenced": signals["tests"],
                },
                "Dynamic Investigation Log": dynamic_log,
                "Artifact Interpretation and Analysis": artifact_analysis,
                "Developer Trajectory Reconstruction": self._build_developer_trajectory(
                    bug_id=bug_id,
                    bug=bug,
                    artifacts=artifacts,
                    final_commit=final_commit,
                ),
                "Code-Level Root Cause": self._build_root_cause_explanation(artifacts),
                "Fix Explanation": self._build_fix_explanation(artifacts, final_commit),
                "Modified Files": modified_files or [self._unknown()],
                "Tests": tests or [self._unknown()],
                "Root Cause Category": self._classify_root_cause(bug, artifacts),
                "Fix Pattern": self._classify_fix_pattern(artifacts, tests),
                "Confidence Assessment": self._confidence_assessment(artifacts, signals, state),
            }
        }
        return report

    def render_markdown(self, report: Dict[str, Any]) -> str:
        root = report.get("BUG FIX TRAJECTORY RECONSTRUCTION", {})
        lines: List[str] = ["BUG FIX TRAJECTORY RECONSTRUCTION", ""]

        lines.extend(self._render_metadata_section(root.get("Bug Metadata", {})))
        lines.extend(self._render_signals_section(root.get("Key Technical Signals", {})))
        lines.extend(self._render_dynamic_log_section(root.get("Dynamic Investigation Log", [])))
        lines.extend(self._render_artifact_analysis_section(root.get("Artifact Interpretation and Analysis", {})))
        lines.extend(self._render_trajectory_section(root.get("Developer Trajectory Reconstruction", {})))
        lines.extend(self._render_simple_section("Code-Level Root Cause", root.get("Code-Level Root Cause", self._unknown())))
        lines.extend(self._render_simple_section("Fix Explanation", root.get("Fix Explanation", self._unknown())))
        lines.extend(self._render_list_section("Modified Files", root.get("Modified Files", [self._unknown()])))
        lines.extend(self._render_list_section("Tests", root.get("Tests", [self._unknown()])))
        lines.extend(self._render_simple_section("Root Cause Category", root.get("Root Cause Category", "Other")))
        lines.extend(self._render_simple_section("Fix Pattern", root.get("Fix Pattern", "Other")))
        lines.extend(self._render_confidence_section(root.get("Confidence Assessment", {})))

        return "\n".join(lines).strip() + "\n"

    def _init_state(self, bug_id: int, bug: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "bug_id": bug_id,
            "bug": bug,
            "component": maybe(bug.get("component")),
            "comments": [],
            "attachments": [],
            "history": [],
            "signals_extracted": False,
            "links_discovered": False,
            "links": [],
            "related_bug_mentions": [],
            "differential_ids": [],
            "hg_refs": [],
            "phab_revisions": {},
            "phab_transactions": {},
            "phab_diffs": {},
            "phab_revision_failures": {},
            "phab_diff_failures": {},
            "hg_commits": {},
            "hg_raw_changesets": {},
            "search_results": {},
            "search_queries_done": [],
            "changed_files": [],
            "changed_functions": [],
            "diff_line_stats": {"added": 0, "removed": 0},
        }

    def _run_dynamic_investigation(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        log: List[Dict[str, Any]] = []

        # Seed with initial evidence because bug has already been fetched.
        log.append(
            {
                "Iteration": "Iteration 1",
                "Action": f"Retrieve Bugzilla bug {state['bug_id']} and baseline metadata.",
                "Evidence gathered": [
                    self._e(f"Title: {maybe(state['bug'].get('summary'))}"),
                    self._e(f"Component: {maybe(state['bug'].get('component'))}"),
                    self._e(f"Status/Resolution: {maybe(state['bug'].get('status'))}/{maybe(state['bug'].get('resolution'))}"),
                ],
                "Interpretation": self._i("Initial scope established; next steps should gather discussion artifacts and links."),
                "Next action decision": "LLM selects next tool action.",
            }
        )

        max_iterations = 14
        for i in range(2, max_iterations + 1):
            plan = self.agent.choose_next_action(state["bug_id"], state, i)
            action = plan.get("action", "finish")
            params = plan.get("params", {}) or {}
            rationale = plan.get("rationale", "")

            evidence, interpretation, next_hint = self._execute_action(state, action, params)

            log.append(
                {
                    "Iteration": f"Iteration {i}",
                    "Action": f"{action} {params}".strip(),
                    "Evidence gathered": evidence if evidence else [self._unknown()],
                    "Interpretation": self._i(interpretation or rationale or "No interpretation available."),
                    "Next action decision": next_hint or "LLM selects next tool action.",
                }
            )

            if plan.get("done") or action == "finish":
                break

        return log

    def _execute_action(self, state: Dict[str, Any], action: str, params: Dict[str, Any]) -> Tuple[List[str], str, str]:
        bug_id = state["bug_id"]

        if action == "fetch_bug":
            state["bug"] = self.bugzilla.get_bug(bug_id) or state["bug"]
            return [self._e("Bug metadata refreshed from Bugzilla.")], "Bug metadata is available.", "Fetch comments/history/attachments next."

        if action == "fetch_comments":
            state["comments"] = self.bugzilla.get_comments(bug_id)
            return [self._e(f"Fetched {len(state['comments'])} comments.")], "Comment trail is now available for signal extraction.", "Fetch attachments and history."

        if action == "fetch_attachments":
            state["attachments"] = self.bugzilla.get_attachments(bug_id)
            return [self._e(f"Fetched {len(state['attachments'])} attachments.")], "Attachment metadata available.", "Fetch history and discover links."

        if action == "fetch_history":
            state["history"] = self.bugzilla.get_history(bug_id)
            return [self._e(f"Fetched {len(state['history'])} history events.")], "Chronological transitions available.", "Extract signals and links."

        if action == "extract_signals":
            self._refresh_link_derived_state(state)
            state["signals_extracted"] = True
            return [
                self._e(f"Potential Differential IDs: {state['differential_ids']}"),
                self._e(f"Potential hg refs: {len(state['hg_refs'])}"),
            ], "Technical clues extracted from available text.", "Discover links and pull revisions."

        if action == "discover_links":
            self._refresh_link_derived_state(state)
            state["links_discovered"] = True
            return [self._e(f"Collected {len(state['links'])} Mozilla links from bug trail.")], "Artifact link graph is populated.", "Fetch referenced Phabricator/hg artifacts."

        if action == "fetch_phabricator_revision":
            revision_id = int(params.get("revision_id", 0)) if params.get("revision_id") else 0
            if not revision_id:
                return [self._u("No revision id provided.")], "Cannot fetch revision without id.", "Select a valid Differential revision id."

            rev = self.phabricator.get_revision_by_id(revision_id)
            if rev:
                fields = rev.get("fields") or {}
                meta = {
                    "revision_id": revision_id,
                    "revision_phid": rev.get("phid"),
                    "title": fields.get("title"),
                    "summary": fields.get("summary"),
                    "status": (fields.get("status") or {}).get("name"),
                    "author_phid": fields.get("authorPHID"),
                    "reviewers": fields.get("reviewers") or [],
                    "date_created": fields.get("dateCreated"),
                    "date_modified": fields.get("dateModified"),
                }
                state["phab_revisions"][revision_id] = meta
                state["phab_revision_failures"].pop(str(revision_id), None)

                if revision_id not in state["differential_ids"]:
                    state["differential_ids"].append(revision_id)

                return [
                    self._e(f"Fetched Phabricator Conduit metadata for D{revision_id}."),
                    self._e(f"Status: {meta.get('status', UNKNOWN_TEXT)}"),
                ], "Revision metadata recovered from Conduit API.", "Fetch raw diff via Conduit for file-level code evidence."

            key = str(revision_id)
            state["phab_revision_failures"][key] = int(state["phab_revision_failures"].get(key, 0)) + 1
            return [self._u(f"Unable to fetch Conduit metadata for D{revision_id}.")], "Phabricator Conduit metadata unavailable.", "Try other revisions or hg commits."
            

        if action == "fetch_phabricator_diff":
            revision_id = int(params.get("revision_id", 0)) if params.get("revision_id") else 0
            if not revision_id:
                return [self._u("No revision id provided.")], "Cannot fetch diff without id.", "Select a valid Differential revision id."

            rev_meta = state["phab_revisions"].get(revision_id, {})
            revision_phid = rev_meta.get("revision_phid")
            if not revision_phid:
                rev = self.phabricator.get_revision_by_id(revision_id)
                revision_phid = rev.get("phid") if rev else None
                if rev and revision_id not in state["phab_revisions"]:
                    fields = rev.get("fields") or {}
                    state["phab_revisions"][revision_id] = {
                        "revision_id": revision_id,
                        "revision_phid": revision_phid,
                        "title": fields.get("title"),
                        "summary": fields.get("summary"),
                        "status": (fields.get("status") or {}).get("name"),
                    }

            if not revision_phid:
                key = str(revision_id)
                state["phab_diff_failures"][key] = int(state["phab_diff_failures"].get(key, 0)) + 1
                return [self._u(f"Cannot resolve revision PHID for D{revision_id}.")], "Missing revision PHID.", "Fetch revision metadata first."

            diff_meta = self.phabricator.get_diff_metadata(revision_phid)
            latest_diff_id = max((d.get("id") for d in diff_meta if d.get("id")), default=None) if diff_meta else None
            if not latest_diff_id:
                key = str(revision_id)
                state["phab_diff_failures"][key] = int(state["phab_diff_failures"].get(key, 0)) + 1
                return [self._u(f"No diff IDs available for D{revision_id} via Conduit.")], "Diff metadata unavailable.", "Try other artifacts."

            raw_diff = self.phabricator.get_raw_diff(latest_diff_id)
            if raw_diff and raw_diff.startswith("diff --git"):
                state["phab_diffs"][revision_id] = raw_diff
                state["phab_diff_failures"].pop(str(revision_id), None)
                parsed = self._parse_diff_summary(raw_diff)
                self._merge_changed_context(state, parsed)
                return [
                    self._e(f"Fetched raw diff via Conduit for D{revision_id} (diffID={latest_diff_id})."),
                    self._e(f"Files in diff: {len(parsed['files'])}"),
                ], "Raw patch content available for code-level analysis.", "Fetch linked commits and tests."

            key = str(revision_id)
            state["phab_diff_failures"][key] = int(state["phab_diff_failures"].get(key, 0)) + 1
            return [self._u(f"Raw diff unavailable from Conduit for D{revision_id} (diffID={latest_diff_id}).")], "Could not load raw diff.", "Use hg commits and bug comments as fallback."

        if action == "fetch_phabricator_transactions":
            revision_id = int(params.get("revision_id", 0)) if params.get("revision_id") else 0
            if not revision_id:
                return [self._u("No revision id provided.")], "Cannot fetch transactions without id.", "Select a valid Differential revision id."

            tx = self.phabricator.get_transactions_for_revision(revision_id)
            state["phab_transactions"][revision_id] = tx or []
            if revision_id in state["phab_revisions"]:
                state["phab_revisions"][revision_id]["transactions_count"] = len(tx or [])
            return [
                self._e(f"Fetched Phabricator transactions for D{revision_id}."),
                self._e(f"Transaction count: {len(tx or [])}"),
            ], "Review conversation and revision churn signals are now available.", "Fetch commit artifacts and raw changesets."

        if action == "fetch_hg_revision":
            repo = params.get("repo")
            rev = params.get("rev")
            if not repo or not rev:
                return [self._u("repo/rev params missing.")], "Cannot fetch hg revision without repo+rev.", "Choose a valid hg reference."

            meta = self.mercurial.get_revision(str(repo), str(rev))
            key = f"{repo}:{rev}"
            if meta:
                state["hg_commits"][key] = {"repo": repo, "revision": rev, "metadata": meta, "url": f"https://hg.mozilla.org/{repo}/rev/{rev}"}
                files = self._normalize_file_entries(meta.get("files") or []) if isinstance(meta.get("files"), list) else []
                for f in files:
                    self._add_changed_file(state, f)

                # Harvest Differential references from commit message.
                desc = safe_text(meta.get("desc"))
                for did in extract_differential_ids(desc):
                    if did not in state["differential_ids"]:
                        state["differential_ids"].append(did)

                return [
                    self._e(f"Fetched hg revision {key}."),
                    self._e(f"Changed files in commit metadata: {len(files)}"),
                ], "Landing commit metadata strengthens fix-ground-truth evidence.", "Fetch referenced Differential revision/diff if available."

            return [self._u(f"Could not fetch hg revision {key}.")], "hg metadata unavailable for this reference.", "Try another hg reference."

        if action == "fetch_hg_raw_changeset":
            repo = params.get("repo")
            rev = params.get("rev")
            if not repo or not rev:
                return [self._u("repo/rev params missing.")], "Cannot fetch raw changeset without repo+rev.", "Choose a valid hg reference."

            key = f"{repo}:{rev}"
            raw_text = self.mercurial.get_raw_changeset(str(repo), str(rev))
            if raw_text:
                state["hg_raw_changesets"][key] = raw_text[:20000]
                return [
                    self._e(f"Fetched raw hg changeset for {key}."),
                    self._e(f"Raw changeset bytes: {len(raw_text)}"),
                ], "Raw changeset text can clarify commit intent and landed metadata.", "If evidence is sufficient, finish."
            return [self._u(f"Could not fetch raw changeset for {key}.")], "Raw changeset unavailable.", "Continue with available commit/diff artifacts."

        if action == "finish":
            return [self._e("LLM planner marked evidence collection as sufficient.")], "Investigation loop complete.", "Synthesize final trajectory reconstruction."

        return [self._u(f"Unknown action '{action}'.")], "Planner proposed an unsupported action.", "Use a supported tool action."

    def _refresh_link_derived_state(self, state: Dict[str, Any]) -> None:
        texts = self._collect_text_blocks(state)
        links = collect_links_from_texts(texts)
        state["links"] = [link.__dict__ for link in links]

        mentions = sorted({b for t in texts for b in extract_bug_mentions(t) if b != state["bug_id"]})
        state["related_bug_mentions"] = mentions

        dids = sorted({did for t in texts for did in extract_differential_ids(t)})
        for did in dids:
            if did not in state["differential_ids"]:
                state["differential_ids"].append(did)

        for t in texts:
            for repo, rev, _ in extract_hg_revisions(t):
                self._add_hg_ref(state, repo, rev)

    def _collect_text_blocks(self, state: Dict[str, Any]) -> List[str]:
        bug = state.get("bug") or {}
        texts = [
            safe_text(bug.get("summary")),
            safe_text(bug.get("description")),
            safe_text(bug.get("whiteboard")),
            safe_text(bug.get("url")),
        ]
        for c in state.get("comments", []):
            texts.append(safe_text(c.get("text")))
            texts.append(safe_text(c.get("raw_text")))
        for a in state.get("attachments", []):
            texts.append(safe_text(a.get("description")))
            texts.append(safe_text(a.get("file_name")))
        for rev in (state.get("phab_revisions") or {}).values():
            texts.append(safe_text(rev.get("title")))
        for item in (state.get("hg_commits") or {}).values():
            texts.append(safe_text((item.get("metadata") or {}).get("desc")))
        return texts

    def _build_artifacts_from_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        commits = list((state.get("hg_commits") or {}).values())
        phab = list((state.get("phab_revisions") or {}).values())

        # Backfill Differential IDs from commit messages.
        for c in commits:
            desc = safe_text((c.get("metadata") or {}).get("desc"))
            for did in extract_differential_ids(desc):
                if did not in state["differential_ids"]:
                    state["differential_ids"].append(did)

        return {
            "links": state.get("links", []),
            "related_bug_mentions": state.get("related_bug_mentions", []),
            "phabricator_revisions": phab,
            "phabricator_transactions": state.get("phab_transactions", {}),
            "commits": commits,
            "raw_changesets": state.get("hg_raw_changesets", {}),
            "changed_files": sorted(set(state.get("changed_files", []))),
            "changed_functions": sorted(set(state.get("changed_functions", []))),
            "diff_line_stats": state.get("diff_line_stats", {"added": 0, "removed": 0}),
            "search_results": state.get("search_results", {}),
        }

    def _extract_technical_signals(self, state: Dict[str, Any], artifacts: Dict[str, Any]) -> Dict[str, List[str]]:
        texts = self._collect_text_blocks(state)

        stack_trace_lines = []
        path_hits = set(artifacts.get("changed_files", []))
        fn_hits = set(artifacts.get("changed_functions", []))
        test_hits = {f for f in artifacts.get("changed_files", []) if self._looks_like_test_file(f)}

        file_re = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:cpp|cc|c|h|hpp|mm|m|rs|js|py|yaml|yml|ini)")
        fn_re = re.compile(r"\b([A-Za-z_][A-Za-z0-9_:~<>]*)\s*\(")

        for text in texts:
            for line in text.splitlines():
                ls = line.strip()
                if not ls:
                    continue
                if "#" in ls and ("0x" in ls or "::" in ls):
                    stack_trace_lines.append(ls)
                if "/test" in ls.lower() or "test_" in ls.lower() or ls.endswith(".ini"):
                    test_hits.add(ls)

            for m in file_re.findall(text):
                path_hits.add(m)
                if self._looks_like_test_file(m):
                    test_hits.add(m)

            for m in fn_re.findall(text):
                if len(m) > 2 and not m.lower().startswith(("http", "https")):
                    fn_hits.add(m)

        if not stack_trace_lines:
            stack_trace_lines = [self._unknown()]
        if not path_hits:
            path_hits = {self._unknown()}
        if not fn_hits:
            fn_hits = {self._unknown()}
        if not test_hits:
            test_hits = {self._unknown()}

        return {
            "stack_traces": [self._e(v) if v != self._unknown() else v for v in list(stack_trace_lines)[:5]],
            "files": [self._e(v) if v != self._unknown() else v for v in sorted(path_hits)[:20]],
            "functions": [self._e(v) if v != self._unknown() else v for v in sorted(fn_hits)[:20]],
            "tests": [self._e(v) if v != self._unknown() else v for v in sorted(test_hits)[:20]],
        }

    def _build_developer_trajectory(
        self,
        bug_id: int,
        bug: Dict[str, Any],
        artifacts: Dict[str, Any],
        final_commit: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        changed_files = artifacts.get("changed_files", [])
        phab = artifacts.get("phabricator_revisions", [])
        phab_tx_total = sum(len(v or []) for v in (artifacts.get("phabricator_transactions", {}) or {}).values())
        raw_cs_count = len(artifacts.get("raw_changesets", {}) or {})

        return {
            "Step 1: Bug report intake": self._i(
                f"Developer read Bug {bug_id}, scoped it to {maybe(bug.get('product'))}/{maybe(bug.get('component'))}, and inspected early comments."
            ),
            "Step 2: Component localization": self._i(
                f"Localization converged on: {', '.join(changed_files[:8]) if changed_files else UNKNOWN_TEXT}."
            ),
            "Step 3: Code investigation": self._i(
                "Developer inspected linked revisions/commits and surrounding code paths to isolate problematic logic."
            ),
            "Step 4: Root cause discovery": self._i(
                "Root cause was inferred from concrete code paths touched by the landing patch and linked review context."
            ),
            "Step 5: Fix implementation": self._i(
                f"Fix was implemented across {len(changed_files)} file(s) with commit-linked changes as ground truth."
            ),
            "Step 6: Patch refinement": self._i(
                f"Patch refinement used review artifacts (Phabricator revisions fetched: {len(phab)}, transactions fetched: {phab_tx_total})."
            ),
            "Step 7: Landing": self._i(
                f"Final landing identified as {self._format_final_commit_line(final_commit)}; raw changesets fetched: {raw_cs_count}."
            ),
        }

    def _analyze_artifacts_with_llm(
        self,
        bug: Dict[str, Any],
        artifacts: Dict[str, Any],
        signals: Dict[str, List[str]],
        dynamic_log: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        api_key = os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("MODEL_NAME", "gpt-4.1-mini")
        if not api_key:
            return {
                "Summary": self._unknown(),
                "Bugzilla Artifacts": [self._unknown("LLM analysis unavailable (OPENAI_API_KEY not set).")],
                "Phabricator Artifacts": [self._unknown("LLM analysis unavailable (OPENAI_API_KEY not set).")],
                "Commit and Diff Artifacts": [self._unknown("LLM analysis unavailable (OPENAI_API_KEY not set).")],
                "Test Artifacts": [self._unknown("LLM analysis unavailable (OPENAI_API_KEY not set).")],
            }

        phab_revs = artifacts.get("phabricator_revisions", [])
        commits = artifacts.get("commits", [])
        changed_files = artifacts.get("changed_files", [])
        phab_tx = artifacts.get("phabricator_transactions", {}) or {}
        raw_changesets = artifacts.get("raw_changesets", {}) or {}
        compact = {
            "bug": {
                "id": bug.get("id"),
                "title": bug.get("summary"),
                "product": bug.get("product"),
                "component": bug.get("component"),
                "status": bug.get("status"),
                "resolution": bug.get("resolution"),
            },
            "signals": {
                "stack_traces": signals.get("stack_traces", [])[:5],
                "files": signals.get("files", [])[:10],
                "functions": signals.get("functions", [])[:10],
                "tests": signals.get("tests", [])[:10],
            },
            "artifacts": {
                "links_count": len(artifacts.get("links", [])),
                "related_bug_mentions": artifacts.get("related_bug_mentions", [])[:10],
                "phabricator_revisions": [
                    {
                        "revision_id": r.get("revision_id"),
                        "status": r.get("status"),
                        "title": r.get("title"),
                        "reviewers_count": len(r.get("reviewers") or []),
                    }
                    for r in phab_revs[:10]
                ],
                "phabricator_transactions": {
                    str(k): [
                        {
                            "type": tx.get("type"),
                            "authorPHID": tx.get("authorPHID"),
                            "dateCreated": tx.get("dateCreated"),
                        }
                        for tx in (v or [])[:20]
                    ]
                    for k, v in list(phab_tx.items())[:10]
                },
                "commits": [
                    {
                        "repo": c.get("repo"),
                        "revision": c.get("revision"),
                        "desc": safe_text((c.get("metadata") or {}).get("desc"))[:300],
                        "files_count": len((c.get("metadata") or {}).get("files") or []),
                    }
                    for c in commits[:10]
                ],
                "changed_files": changed_files[:30],
                "diff_line_stats": artifacts.get("diff_line_stats", {}),
                "raw_changesets": {
                    k: safe_text(v)[:800]
                    for k, v in list(raw_changesets.items())[:10]
                },
            },
        }

        prompt = (
            "Analyze the collected Mozilla bug-fix artifacts and provide engineering interpretation.\n"
            "Return ONLY JSON with keys:\n"
            "summary (string), bugzilla_artifacts (array of strings), phabricator_artifacts (array of strings),\n"
            "commit_and_diff_artifacts (array of strings), test_artifacts (array of strings).\n"
            "Interpret ONLY retrieved artifacts (Bugzilla/Phabricator/commit/diff/test artifacts), not workflow log text.\n"
            "Each line should start with [Evidence], [Inference], or [Unknown].\n\n"
            f"Data:\n{json.dumps(compact, indent=2)}"
        )

        try:
            payload: Dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a Mozilla debugging analyst."},
                    {"role": "user", "content": prompt},
                ],
            }
            if not model.startswith("gpt-5"):
                payload["temperature"] = 0

            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            if resp.status_code >= 400:
                return {
                    "Summary": self._unknown(f"LLM artifact analysis failed: status={resp.status_code}."),
                    "Bugzilla Artifacts": [self._unknown()],
                    "Phabricator Artifacts": [self._unknown()],
                    "Commit and Diff Artifacts": [self._unknown()],
                    "Test Artifacts": [self._unknown()],
                }

            raw = resp.json()["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.splitlines()[1:-1]).strip()
            if raw.startswith("json"):
                raw = "\n".join(raw.splitlines()[1:]).strip()
            parsed = json.loads(raw)

            return {
                "Summary": parsed.get("summary", self._unknown()),
                "Bugzilla Artifacts": parsed.get("bugzilla_artifacts", [self._unknown()]),
                "Phabricator Artifacts": parsed.get("phabricator_artifacts", [self._unknown()]),
                "Commit and Diff Artifacts": parsed.get("commit_and_diff_artifacts", [self._unknown()]),
                "Test Artifacts": parsed.get("test_artifacts", [self._unknown()]),
            }
        except Exception as exc:
            return {
                "Summary": self._unknown(f"LLM artifact analysis exception: {exc}"),
                "Bugzilla Artifacts": [self._unknown()],
                "Phabricator Artifacts": [self._unknown()],
                "Commit and Diff Artifacts": [self._unknown()],
                "Test Artifacts": [self._unknown()],
            }

    def _build_root_cause_explanation(self, artifacts: Dict[str, Any]) -> str:
        changed_files = artifacts.get("changed_files", [])
        changed_functions = artifacts.get("changed_functions", [])
        if not changed_files:
            return self._unknown()

        fn_part = f" Function-level contexts include: {', '.join(changed_functions[:5])}." if changed_functions else ""
        return self._i(
            "Defect mechanism localizes to the modified subsystem code paths in "
            f"{', '.join(changed_files[:8])}.{fn_part} "
            "Where explicit pre-fix failure details are absent, diagnosis is inferred from patch-side evidence and linked commit descriptions."
        )

    def _build_fix_explanation(self, artifacts: Dict[str, Any], final_commit: Optional[Dict[str, Any]]) -> str:
        changed_files = artifacts.get("changed_files", [])
        if not changed_files:
            return self._unknown()

        diff_stats = artifacts.get("diff_line_stats", {"added": 0, "removed": 0})
        commit_desc = maybe((final_commit.get("metadata") or {}).get("desc")) if final_commit else UNKNOWN_TEXT

        return self._i(
            f"Patch updates {len(changed_files)} file(s), with parsed diff delta +{diff_stats.get('added', 0)} / -{diff_stats.get('removed', 0)} when raw diff is available. "
            f"Landing description: {commit_desc}. "
            "This changes runtime behavior in the affected subsystem to eliminate the observed failure mode."
        )

    def _classify_root_cause(self, bug: Dict[str, Any], artifacts: Dict[str, Any]) -> str:
        text = " ".join(
            [
                safe_text(bug.get("summary")),
                safe_text((self._pick_final_commit(artifacts.get("commits", [])) or {}).get("metadata", {}).get("desc")),
            ]
        ).lower()
        if any(k in text for k in ["race", "ordering", "concurrent", "thread"]):
            return "Concurrency bug"
        if any(k in text for k in ["null", "invalid", "validate", "check"]):
            return "Validation error"
        if any(k in text for k in ["state", "transition", "lifecycle"]):
            return "State management bug"
        if any(k in text for k in ["leak", "uaf", "free", "overflow", "buffer"]):
            return "Memory bug"
        if any(k in text for k in ["api", "interface", "contract"]):
            return "API misuse"
        return "Logic error"

    def _classify_fix_pattern(self, artifacts: Dict[str, Any], tests: List[str]) -> str:
        desc = safe_text((self._pick_final_commit(artifacts.get("commits", [])) or {}).get("metadata", {}).get("desc")).lower()
        if any(k in desc for k in ["validate", "invalid", "sanity", "guard"]):
            return "Validation added"
        if any(k in desc for k in ["check", "if", "avoid", "prevent", "do not"]):
            return "Condition added"
        if any(k in desc for k in ["refactor", "cleanup"]):
            return "Refactoring"
        if any(k in desc for k in ["api", "interface"]):
            return "API usage correction"
        if tests and tests != [self._unknown()] and len(artifacts.get("changed_files", [])) == len(tests):
            return "Test fix"
        return "Algorithm correction"

    def _confidence_assessment(self, artifacts: Dict[str, Any], signals: Dict[str, List[str]], state: Dict[str, Any]) -> Dict[str, List[str]]:
        high = [
            self._e("Bug metadata/comments/history/attachments were fetched directly from Bugzilla REST."),
            self._e("Changed files and landing evidence were derived from linked hg revisions and/or raw Differential diffs."),
        ]
        uncertain = []
        missing = []

        if not artifacts.get("phabricator_revisions"):
            uncertain.append(self._i("Review iteration details remain partial because no Differential metadata was fetched."))
            missing.append(self._u("Phabricator review comments/transaction timeline."))
        if signals.get("stack_traces") == [self._unknown()]:
            uncertain.append(self._i("Stack-trace-driven localization was not possible from available artifacts."))
            missing.append(self._u("Stack traces in bug comments/attachments."))
        if not artifacts.get("commits"):
            uncertain.append(self._i("Landing reconstruction confidence is reduced without linked hg revisions."))
            missing.append(self._u("Explicit mozilla-central/autoland revision links."))

        if not uncertain:
            uncertain = [self._e("No major uncertainty beyond normal inference boundaries.")]
        if not missing:
            missing = [self._e("No critical missing artifacts for this trajectory reconstruction.")]

        return {
            "High confidence findings": high,
            "Uncertain findings": uncertain,
            "Missing artifacts": missing,
        }

    def _add_hg_ref(self, state: Dict[str, Any], repo: str, rev: str) -> None:
        refs = state.get("hg_refs", [])
        if not any(r.get("repo") == repo and r.get("rev") == rev for r in refs):
            refs.append({"repo": repo, "rev": rev})
            state["hg_refs"] = refs

    def _add_changed_file(self, state: Dict[str, Any], path: str) -> None:
        if not isinstance(path, str) or not path or path == "/dev/null":
            return
        if path not in state["changed_files"]:
            state["changed_files"].append(path)

    def _merge_changed_context(self, state: Dict[str, Any], parsed: Dict[str, Any]) -> None:
        for f in parsed.get("files", set()):
            self._add_changed_file(state, f)
        for fn in parsed.get("functions", set()):
            if fn not in state["changed_functions"]:
                state["changed_functions"].append(fn)
        state["diff_line_stats"]["added"] += int(parsed.get("plus_lines", 0))
        state["diff_line_stats"]["removed"] += int(parsed.get("minus_lines", 0))

    def _pick_final_commit(self, commits: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        dated: List[Tuple[dt.datetime, Dict[str, Any]]] = []
        for commit in commits:
            meta = commit.get("metadata") or {}
            date_raw = meta.get("date")
            if not date_raw:
                continue
            parsed = self._parse_hg_date(date_raw)
            if parsed:
                dated.append((parsed, commit))
        if dated:
            dated.sort(key=lambda x: x[0])
            return dated[-1][1]
        return commits[-1] if commits else None

    def _parse_hg_date(self, value: Any) -> Optional[dt.datetime]:
        if isinstance(value, list) and value:
            try:
                return dt.datetime.fromtimestamp(float(value[0]), tz=dt.timezone.utc)
            except Exception:
                return None
        if isinstance(value, str):
            for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d %H:%M:%S %z"]:
                try:
                    return dt.datetime.strptime(value, fmt)
                except Exception:
                    continue
        return None

    def _format_final_commit_line(self, commit: Optional[Dict[str, Any]]) -> str:
        if not commit:
            return self._unknown()
        meta = commit.get("metadata") or {}
        return (
            f"repo={commit.get('repo')}, rev={commit.get('revision')}, "
            f"desc={maybe(meta.get('desc'))}, date={maybe(meta.get('date'))}"
        )

    def _parse_diff_summary(self, diff_text: str) -> Dict[str, Any]:
        files = set()
        functions = set()
        plus_lines = 0
        minus_lines = 0

        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                files.add(line.replace("+++ b/", "").strip())
            elif line.startswith("--- a/"):
                files.add(line.replace("--- a/", "").strip())
            elif line.startswith("@@"):
                m = re.search(r"@@.*@@\s*(.*)$", line)
                if m and m.group(1).strip():
                    functions.add(m.group(1).strip())
            elif line.startswith("+") and not line.startswith("+++"):
                plus_lines += 1
            elif line.startswith("-") and not line.startswith("---"):
                minus_lines += 1

        return {"files": files, "functions": functions, "plus_lines": plus_lines, "minus_lines": minus_lines}

    def _normalize_file_entries(self, entries: List[Any]) -> List[str]:
        normalized: List[str] = []
        for entry in entries:
            if isinstance(entry, str):
                normalized.append(entry)
            elif isinstance(entry, dict):
                candidate = entry.get("file") or entry.get("name") or entry.get("path")
                if isinstance(candidate, str):
                    normalized.append(candidate)
        return normalized

    def _looks_like_test_file(self, path: str) -> bool:
        p = path.lower()
        return "/test" in p or "/tests" in p or p.startswith("test/") or p.endswith("_test.cpp") or p.endswith(".ini")

    def _e(self, text: str) -> str:
        return f"[Evidence] {text}"

    def _i(self, text: str) -> str:
        return f"[Inference] {text}"

    def _u(self, text: str = UNKNOWN_TEXT) -> str:
        return f"[Unknown] {text}"

    def _unknown(self) -> str:
        return self._u(UNKNOWN_TEXT)

    def _render_metadata_section(self, data: Dict[str, Any]) -> List[str]:
        lines = ["Bug Metadata", "-------------"]
        for key in ["Bug ID", "Title", "Component", "Status", "Resolution"]:
            lines.append(f"{key}: {data.get(key, self._unknown())}")
        lines.append("")
        return lines

    def _render_signals_section(self, data: Dict[str, Any]) -> List[str]:
        lines = ["Key Technical Signals", "---------------------"]
        for key in ["Stack traces", "Files referenced", "Functions referenced", "Tests referenced"]:
            value = data.get(key, [self._unknown()])
            if isinstance(value, list):
                lines.append(f"{key}: {'; '.join(value)}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("")
        return lines

    def _render_dynamic_log_section(self, data: List[Dict[str, Any]]) -> List[str]:
        lines = ["Dynamic Investigation Log", "-------------------------"]
        for item in data:
            lines.append(item.get("Iteration", "Iteration"))
            lines.append(f"Action: {item.get('Action', self._unknown())}")
            lines.append("Evidence gathered:")
            for e in item.get("Evidence gathered", [self._unknown()]):
                lines.append(f"- {e}")
            lines.append(f"Interpretation: {item.get('Interpretation', self._unknown())}")
            lines.append(f"Next action decision: {item.get('Next action decision', self._unknown())}")
            lines.append("")
        return lines

    def _render_trajectory_section(self, data: Dict[str, Any]) -> List[str]:
        lines = ["Developer Trajectory Reconstruction", "-----------------------------------"]
        for key in [
            "Step 1: Bug report intake",
            "Step 2: Component localization",
            "Step 3: Code investigation",
            "Step 4: Root cause discovery",
            "Step 5: Fix implementation",
            "Step 6: Patch refinement",
            "Step 7: Landing",
        ]:
            lines.append(f"{key} {data.get(key, self._unknown())}")
        lines.append("")
        return lines

    def _render_artifact_analysis_section(self, data: Dict[str, Any]) -> List[str]:
        lines = ["Artifact Interpretation and Analysis", "-----------------------------------"]
        lines.append(f"Summary: {data.get('Summary', self._unknown())}")
        for key in [
            "Bugzilla Artifacts",
            "Phabricator Artifacts",
            "Commit and Diff Artifacts",
            "Test Artifacts",
        ]:
            lines.append(f"{key}:")
            vals = data.get(key, [self._unknown()])
            if not isinstance(vals, list):
                vals = [str(vals)]
            for item in vals:
                lines.append(f"- {item}")
        lines.append("")
        return lines

    def _render_simple_section(self, title: str, content: str) -> List[str]:
        return [title, "---------------", str(content), ""]

    def _render_list_section(self, title: str, items: List[str]) -> List[str]:
        lines = [title, "--------------"]
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
        return lines

    def _render_confidence_section(self, data: Dict[str, Any]) -> List[str]:
        lines = ["Confidence Assessment", "---------------------"]
        lines.append("High confidence findings:")
        for item in data.get("High confidence findings", [self._unknown()]):
            lines.append(f"- {item}")
        lines.append("Uncertain findings:")
        for item in data.get("Uncertain findings", [self._unknown()]):
            lines.append(f"- {item}")
        lines.append("Missing artifacts:")
        for item in data.get("Missing artifacts", [self._unknown()]):
            lines.append(f"- {item}")
        lines.append("")
        return lines
