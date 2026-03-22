from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

from .llm_refiner import OpenAICompatibleLLMClient
from .mozilla_repo_client import MercurialClient, SearchfoxClient


PATH_RE = re.compile(r"\b(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:c|cc|cpp|h|hh|hpp|mm|m|idl|js|jsm|ts|rs|py|yaml|yml|ini|conf|xhtml)\b")
SYMBOL_RE = re.compile(r"\b(?:[A-Za-z_]\w*::)+[A-Za-z_]\w*\b|\b[A-Za-z_]\w+\([A-Za-z_][^)\n]{0,80}\)")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


@dataclass
class RetrievalSignals:
    explicit_paths: List[str]
    explicit_symbols: List[str]
    explicit_queries: List[str]


@dataclass
class RetrievedCodeRegion:
    repo: str
    path: str
    symbol: str
    source: str
    start_line: int
    end_line: int
    content: str
    retrieval_reason: str
    match_type: str
    confidence: float
    query_support: List[str]
    code_hit_count: int
    comment_hit_count: int


class TraceFixAgent:
    def __init__(
        self,
        *,
        model: str,
        mercurial_client: Optional[MercurialClient] = None,
        searchfox_client: Optional[SearchfoxClient] = None,
    ):
        self.client = OpenAICompatibleLLMClient(model=model)
        self.mercurial = mercurial_client or MercurialClient()
        self.searchfox = searchfox_client or SearchfoxClient()

    def generate_fix(
        self,
        *,
        bug: Dict[str, Any],
        comments: Sequence[Dict[str, Any]],
        attachments: Sequence[Dict[str, Any]],
        trace: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._build_context(
            bug=bug,
            comments=comments,
            attachments=attachments,
            trace=trace,
        )
        signals = self._collect_explicit_signals(context)
        plan = self._plan(context, signals)
        profile = self._profile_bug_and_fix_pattern(context, plan)
        local_candidates = self._retrieve_local(plan, profile, context, signals)
        analogical_candidates = self._retrieve_analogical(plan, profile, context, signals)
        ranked_candidates = self._rerank_candidates(
            local_candidates + analogical_candidates,
            plan=plan,
            profile=profile,
            context=context,
            signals=signals,
        )
        diff = self._generate_patch(
            context=context,
            plan=plan,
            profile=profile,
            ranked_candidates=ranked_candidates,
        )
        return {
            "plan": plan,
            "profile": profile,
            "retrieval_signals": asdict(signals),
            "ranked_candidates": ranked_candidates,
            "retrieved_context": {
                "regions": [
                    candidate["region"]
                    for candidate in ranked_candidates[:6]
                ]
            },
            "diff": self._extract_diff(diff),
        }

    def _build_context(
        self,
        *,
        bug: Dict[str, Any],
        comments: Sequence[Dict[str, Any]],
        attachments: Sequence[Dict[str, Any]],
        trace: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "bug": {
                "id": bug.get("id"),
                "title": bug.get("summary"),
                "product": bug.get("product"),
                "component": bug.get("component"),
                "description": self._safe_text(bug.get("description")),
            },
            "comments": [
                {
                    "author": item.get("creator"),
                    "time": item.get("time"),
                    "text": self._safe_text(item.get("text")),
                }
                for item in comments[:25]
            ],
            "attachments": [
                {
                    "id": item.get("id"),
                    "summary": self._safe_text(item.get("summary") or item.get("description")),
                    "is_patch": bool(item.get("is_patch")),
                    "content_type": item.get("content_type"),
                }
                for item in attachments[:10]
            ],
            "trace": trace,
        }

    def _plan(self, context: Dict[str, Any], signals: RetrievalSignals) -> Dict[str, Any]:
        prompt = json.dumps(
            {
                "task": "plan_mozilla_bug_fix",
                "context": {
                    "bug": context["bug"],
                    "comments": context["comments"][:10],
                    "trace": {
                        "title": context["trace"].get("title"),
                        "summary": context["trace"].get("summary"),
                        "derived_milestone_trace": context["trace"].get("derived_milestone_trace", [])[:8],
                    },
                    "retrieval_signals": asdict(signals),
                },
                "requirements": {
                    "produce": [
                        "problem_summary",
                        "repo_hint",
                        "candidate_symbols",
                        "candidate_queries",
                        "candidate_files",
                        "fix_hypothesis",
                        "root_cause_category",
                        "fix_pattern_category",
                        "expected_edit_operations",
                        "expected_scope",
                        "analogical_queries",
                    ],
                    "repo_hint_values": ["mozilla-central", "comm-central"],
                    "expected_scope_values": ["small_local_fix", "medium_local_fix", "broad_refactor"],
                    "limits": {
                        "candidate_symbols": 8,
                        "candidate_queries": 8,
                        "candidate_files": 8,
                        "analogical_queries": 8,
                    },
                },
            },
            indent=2,
        )
        response = self.client.complete_json(
            "You plan local and analogical retrieval for a Mozilla bug-fix agent. Return compact JSON only.",
            prompt,
        )
        return {
            "problem_summary": self._safe_text(response.get("problem_summary")),
            "repo_hint": response.get("repo_hint") if response.get("repo_hint") in {"mozilla-central", "comm-central"} else "mozilla-central",
            "candidate_symbols": self._normalize_list(response.get("candidate_symbols"), limit=8),
            "candidate_queries": self._normalize_list(response.get("candidate_queries"), limit=8),
            "candidate_files": self._normalize_paths(response.get("candidate_files"), limit=8),
            "fix_hypothesis": self._safe_text(response.get("fix_hypothesis")),
            "root_cause_category": self._safe_text(response.get("root_cause_category")),
            "fix_pattern_category": self._safe_text(response.get("fix_pattern_category")),
            "expected_edit_operations": self._normalize_list(response.get("expected_edit_operations"), limit=8),
            "expected_scope": self._safe_text(response.get("expected_scope")) or "small_local_fix",
            "analogical_queries": self._normalize_list(response.get("analogical_queries"), limit=8),
        }

    def _profile_bug_and_fix_pattern(self, context: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
        prompt = json.dumps(
            {
                "task": "profile_bug_and_fix_pattern",
                "bug": context["bug"],
                "trace_summary": {
                    "title": context["trace"].get("title"),
                    "summary": context["trace"].get("summary"),
                    "derived_milestone_trace": context["trace"].get("derived_milestone_trace", [])[:8],
                },
                "plan": plan,
                "output_schema": {
                    "bug_pattern": "snake_case label",
                    "root_cause_category": "snake_case label",
                    "fix_pattern_category": "snake_case label",
                    "edit_operations": ["snake_case op"],
                    "expected_code_roles": ["role"],
                    "confidence": "0..1 float",
                },
            },
            indent=2,
        )
        response = self.client.complete_json(
            "You classify Mozilla bugs into reusable repair-pattern categories. Return JSON only.",
            prompt,
        )
        confidence = response.get("confidence", 0.5)
        try:
            confidence_value = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence_value = 0.5
        return {
            "bug_pattern": self._safe_text(response.get("bug_pattern")),
            "root_cause_category": self._safe_text(response.get("root_cause_category")) or plan.get("root_cause_category", ""),
            "fix_pattern_category": self._safe_text(response.get("fix_pattern_category")) or plan.get("fix_pattern_category", ""),
            "edit_operations": self._normalize_list(response.get("edit_operations"), limit=8) or list(plan.get("expected_edit_operations", [])),
            "expected_code_roles": self._normalize_list(response.get("expected_code_roles"), limit=8),
            "confidence": confidence_value,
        }

    def _retrieve_local(
        self,
        plan: Dict[str, Any],
        profile: Dict[str, Any],
        context: Dict[str, Any],
        signals: RetrievalSignals,
    ) -> List[RetrievedCodeRegion]:
        repo_hint = plan["repo_hint"]
        path_candidates = self._dedupe_paths([*signals.explicit_paths, *plan["candidate_files"]])[:10]
        query_candidates = self._dedupe_texts(
            [
                *signals.explicit_queries,
                *signals.explicit_symbols,
                *plan["candidate_queries"],
                *plan["candidate_symbols"],
                context["bug"]["title"],
                context["bug"]["component"],
                context["bug"]["product"],
                plan["problem_summary"],
                *self._query_fragments(context["bug"].get("description", "")),
            ]
        )[:12]
        search_results = self._search_queries(repo_hint, query_candidates, match_type="local")
        for result in search_results:
            path_candidates.append(result["path"])
        return self._materialize_regions(
            repo_hint=repo_hint,
            candidate_paths=self._dedupe_paths(path_candidates),
            symbol_needles=self._dedupe_texts([*signals.explicit_symbols, *plan["candidate_symbols"]]),
            query_needles=query_candidates,
            search_results=search_results,
            match_type="local",
            default_reason="same subsystem / likely local repair region",
            max_regions=8,
        )

    def _retrieve_analogical(
        self,
        plan: Dict[str, Any],
        profile: Dict[str, Any],
        context: Dict[str, Any],
        signals: RetrievalSignals,
    ) -> List[RetrievedCodeRegion]:
        repo_hint = plan["repo_hint"]
        analogical_queries = self._dedupe_texts(
            [
                *plan.get("analogical_queries", []),
                *self._make_profile_queries(plan, profile),
            ]
        )[:12]
        search_results = self._search_queries(repo_hint, analogical_queries, match_type="analogical")
        candidate_paths = self._dedupe_paths([item["path"] for item in search_results])
        return self._materialize_regions(
            repo_hint=repo_hint,
            candidate_paths=candidate_paths,
            symbol_needles=list(plan["candidate_symbols"]),
            query_needles=analogical_queries,
            search_results=search_results,
            match_type="analogical",
            default_reason="same semantic repair pattern or analogous code role",
            max_regions=8,
        )

    def _search_queries(self, repo_hint: str, queries: Sequence[str], match_type: str) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for query in queries:
            for item in self.searchfox.search(query=query, repo=repo_hint, limit=6):
                path = item.get("path")
                if not path:
                    continue
                results.append(
                    {
                        "path": path,
                        "query": query,
                        "match_type": match_type,
                    }
                )
        deduped: List[Dict[str, str]] = []
        seen = set()
        for item in results:
            key = (item["path"], item["query"], item["match_type"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _materialize_regions(
        self,
        *,
        repo_hint: str,
        candidate_paths: Sequence[str],
        symbol_needles: Sequence[str],
        query_needles: Sequence[str],
        search_results: Sequence[Dict[str, str]],
        match_type: str,
        default_reason: str,
        max_regions: int,
    ) -> List[RetrievedCodeRegion]:
        regions: List[RetrievedCodeRegion] = []
        for path in candidate_paths[:10]:
            content = self.mercurial.get_raw_file(repo_hint, "tip", path)
            if not content:
                continue
            file_regions = self._extract_regions_from_file(
                repo=repo_hint,
                path=path,
                content=content,
                symbol_needles=symbol_needles,
                query_needles=query_needles,
                search_results=[item for item in search_results if item["path"] == path],
                match_type=match_type,
                default_reason=default_reason,
            )
            regions.extend(file_regions)
            if len(regions) >= max_regions * 2:
                break
        return self._dedupe_regions(regions)[:max_regions]

    def _extract_regions_from_file(
        self,
        *,
        repo: str,
        path: str,
        content: str,
        symbol_needles: Sequence[str],
        query_needles: Sequence[str],
        search_results: Sequence[Dict[str, str]],
        match_type: str,
        default_reason: str,
    ) -> List[RetrievedCodeRegion]:
        lines = content.splitlines()
        if not lines:
            return []

        matches: List[tuple[int, str, str, str]] = []
        for symbol in symbol_needles[:8]:
            for line_no in self._find_line_matches(lines, symbol):
                matches.append((line_no, symbol, f"{match_type}: symbol overlap with `{symbol}`", symbol))
        for query in query_needles[:8]:
            reason = self._reason_for_query(query, default_reason, match_type)
            for line_no in self._find_line_matches(lines, query):
                matches.append((line_no, self._symbol_hint_from_query(query, path), reason, query))

        if not matches:
            return []

        regions: List[RetrievedCodeRegion] = []
        used_windows = set()
        path_queries = self._dedupe_texts([item["query"] for item in search_results if item.get("query")])
        for line_no, symbol, reason, query in matches[:12]:
            start = max(1, line_no - 20)
            end = min(len(lines), line_no + 20)
            window_key = (start, end)
            if window_key in used_windows:
                continue
            used_windows.add(window_key)
            snippet = "\n".join(f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1))
            confidence = 0.85 if "symbol overlap" in reason else 0.65
            code_hit_count, comment_hit_count = self._window_hit_quality(lines, start, end, query)
            regions.append(
                RetrievedCodeRegion(
                    repo=repo,
                    path=path,
                    symbol=symbol or path.rsplit("/", 1)[-1],
                    source="hg-raw-file-region",
                    start_line=start,
                    end_line=end,
                    content=snippet[:6000],
                    retrieval_reason=reason,
                    match_type=match_type,
                    confidence=confidence,
                    query_support=self._dedupe_texts([query, *path_queries])[:8],
                    code_hit_count=code_hit_count,
                    comment_hit_count=comment_hit_count,
                )
            )
            if len(regions) >= 3:
                break
        return regions

    def _rerank_candidates(
        self,
        candidates: Sequence[RetrievedCodeRegion],
        *,
        plan: Dict[str, Any],
        profile: Dict[str, Any],
        context: Dict[str, Any],
        signals: RetrievalSignals,
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        family_support = self._family_support(candidates)
        ranked_output: List[Dict[str, Any]] = []
        for candidate in candidates[:24]:
            breakdown = self._heuristic_breakdown(
                candidate=candidate,
                plan=plan,
                profile=profile,
                context=context,
                signals=signals,
                family_support=family_support,
            )
            score = (
                0.22 * breakdown["query_support"]
                + 0.18 * breakdown["subsystem_compatibility"]
                + 0.16 * breakdown["explicit_path_signal"]
                + 0.14 * breakdown["symbol_overlap"]
                + 0.12 * breakdown["code_role_match"]
                + 0.10 * breakdown["fix_pattern_match"]
                + 0.08 * breakdown["analogical_support"]
                + 0.07 * breakdown["root_cause_match"]
                + 0.07 * breakdown["family_support"]
                + 0.06 * breakdown["code_hit_quality"]
                + 0.05 * breakdown["scope_compatibility"]
                - 0.20 * breakdown["superficial_similarity_penalty"]
            )
            reason_labels = self._reason_labels(candidate, breakdown)
            ranked_output.append(
                {
                    "score": round(score, 4),
                    "score_breakdown": breakdown,
                    "match_strength": self._match_strength(score),
                    "reason_labels": reason_labels,
                    "reason": self._build_reason(candidate, breakdown, reason_labels),
                    "region": asdict(candidate),
                }
            )

        ranked_output.sort(key=lambda item: item["score"], reverse=True)
        return ranked_output[:8]

    def _generate_patch(
        self,
        *,
        context: Dict[str, Any],
        plan: Dict[str, Any],
        profile: Dict[str, Any],
        ranked_candidates: Sequence[Dict[str, Any]],
    ) -> str:
        allowed_paths = self._allowed_patch_paths(ranked_candidates)
        prompt = self._build_patch_prompt(
            context=context,
            plan=plan,
            profile=profile,
            ranked_candidates=ranked_candidates,
            allowed_paths=allowed_paths,
            retry_reason=None,
        )
        response = self.client.complete_json(
            "You write grounded Mozilla fixes from ranked local and analogical code regions. Return valid JSON only with key diff.",
            prompt,
        )
        diff = response.get("diff", "")
        if not isinstance(diff, str) or not diff.strip():
            raise RuntimeError("Fix agent did not return a diff.")
        diff = self._extract_diff(diff)

        verification = self._verify_patch(
            diff=diff,
            ranked_candidates=ranked_candidates,
            allowed_paths=allowed_paths,
            bug=context["bug"],
            plan=plan,
            profile=profile,
        )
        if verification["accepted"]:
            return diff

        retry_prompt = self._build_patch_prompt(
            context=context,
            plan=plan,
            profile=profile,
            ranked_candidates=ranked_candidates,
            allowed_paths=allowed_paths,
            retry_reason=verification["reason"],
        )
        retry_response = self.client.complete_json(
            "You write grounded Mozilla fixes from ranked local and analogical code regions. Return valid JSON only with key diff.",
            retry_prompt,
        )
        retry_diff = retry_response.get("diff", "")
        if not isinstance(retry_diff, str) or not retry_diff.strip():
            raise RuntimeError("Fix agent retry did not return a diff.")
        retry_diff = self._extract_diff(retry_diff)
        retry_verification = self._verify_patch(
            diff=retry_diff,
            ranked_candidates=ranked_candidates,
            allowed_paths=allowed_paths,
            bug=context["bug"],
            plan=plan,
            profile=profile,
        )
        return retry_diff if retry_verification["accepted"] else diff

    def _build_patch_prompt(
        self,
        *,
        context: Dict[str, Any],
        plan: Dict[str, Any],
        profile: Dict[str, Any],
        ranked_candidates: Sequence[Dict[str, Any]],
        allowed_paths: Sequence[str],
        retry_reason: Optional[str],
    ) -> str:
        constraints = [
            "Prefer the strongest local candidate unless analogical evidence clearly suggests a better repair shape.",
            "Use the retrieval reasons, code roles, and score breakdowns explicitly.",
            "Operate on retrieved regions rather than inventing unrelated files.",
            "Modify only these allowed paths unless you include an explicit OVERRIDE_PATH line before the diff: "
            + ", ".join(allowed_paths),
            "Return JSON with a single key diff containing only a unified diff.",
            "Do not use placeholder comments or pseudo-code.",
        ]
        if retry_reason:
            constraints.append(f"Previous attempt was rejected: {retry_reason}")
            constraints.append("Stay strictly within the highest-ranked allowed path if possible.")
        return json.dumps(
            {
                "task": "generate_grounded_mozilla_fix",
                "bug": context["bug"],
                "plan": plan,
                "profile": profile,
                "comments": context["comments"][:12],
                "trace_summary": {
                    "title": context["trace"].get("title"),
                    "derived_milestone_trace": context["trace"].get("derived_milestone_trace", [])[:8],
                },
                "ranked_candidates": list(ranked_candidates)[:6],
                "allowed_paths": list(allowed_paths),
                "constraints": constraints,
            },
            indent=2,
        )

    def _verify_patch(
        self,
        *,
        diff: str,
        ranked_candidates: Sequence[Dict[str, Any]],
        allowed_paths: Sequence[str],
        bug: Dict[str, Any],
        plan: Dict[str, Any],
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        touched_paths = self._parse_diff_paths(diff)
        allowed_set = set(allowed_paths)
        if touched_paths and all(path in allowed_set for path in touched_paths):
            return {"accepted": True, "reason": "touched paths stay within allowed candidates"}

        prompt = json.dumps(
            {
                "task": "verify_grounded_patch_alignment",
                "bug": bug,
                "plan": plan,
                "profile": profile,
                "allowed_paths": list(allowed_paths),
                "ranked_candidates": list(ranked_candidates)[:4],
                "touched_paths": touched_paths,
                "diff": diff,
                "output_schema": {
                    "accepted": "true|false",
                    "reason": "brief explanation",
                },
            },
            indent=2,
        )
        response = self.client.complete_json(
            "You verify whether a generated Mozilla patch stays aligned with top-ranked retrieval candidates. Return JSON only.",
            prompt,
        )
        accepted = bool(response.get("accepted"))
        reason = self._safe_text(response.get("reason")) or "patch diverged from top-ranked candidates"
        return {"accepted": accepted, "reason": reason}

    def _allowed_patch_paths(self, ranked_candidates: Sequence[Dict[str, Any]]) -> List[str]:
        local_paths: List[str] = []
        all_paths: List[str] = []
        for item in ranked_candidates:
            region = item.get("region", {})
            path = self._safe_text(region.get("path"))
            if not path:
                continue
            all_paths.append(path)
            if self._safe_text(region.get("match_type")) == "local":
                local_paths.append(path)
        preferred = self._dedupe_paths(local_paths)[:2]
        if preferred:
            return preferred
        return self._dedupe_paths(all_paths)[:2]

    def _parse_diff_paths(self, diff: str) -> List[str]:
        paths: List[str] = []
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                paths.append(line[6:].strip())
        return self._dedupe_paths(paths)

    def _collect_explicit_signals(self, context: Dict[str, Any]) -> RetrievalSignals:
        texts: List[str] = [
            self._safe_text(context["bug"].get("title")),
            self._safe_text(context["bug"].get("description")),
            self._safe_text(context["trace"].get("title")),
            self._safe_text(context["trace"].get("summary")),
        ]
        for comment in context.get("comments", []):
            texts.append(self._safe_text(comment.get("text")))
        for attachment in context.get("attachments", []):
            texts.append(self._safe_text(attachment.get("summary")))
        for milestone in context["trace"].get("derived_milestone_trace", []):
            texts.append(self._safe_text(milestone.get("notes")))
            for evidence in milestone.get("evidence", []):
                texts.append(self._safe_text(evidence.get("normalized_summary")))
                texts.append(self._safe_text(evidence.get("raw_snippet")))

        paths: List[str] = []
        symbols: List[str] = []
        queries: List[str] = []
        for text in texts:
            paths.extend(PATH_RE.findall(text))
            symbols.extend(SYMBOL_RE.findall(text))
            queries.extend(self._query_fragments(text))

        return RetrievalSignals(
            explicit_paths=self._dedupe_paths(paths),
            explicit_symbols=self._dedupe_texts([item.replace("(", "").replace(")", "") for item in symbols])[:12],
            explicit_queries=self._dedupe_texts(queries)[:16],
        )

    def _make_profile_queries(self, plan: Dict[str, Any], profile: Dict[str, Any]) -> List[str]:
        queries = [
            plan.get("fix_pattern_category", ""),
            plan.get("root_cause_category", ""),
            profile.get("bug_pattern", ""),
            profile.get("fix_pattern_category", ""),
            profile.get("root_cause_category", ""),
            " ".join(profile.get("edit_operations", [])),
            " ".join(profile.get("expected_code_roles", [])),
        ]
        template_queries: List[str] = []
        if profile.get("fix_pattern_category"):
            template_queries.append(f"{profile['fix_pattern_category']} mozilla")
        if profile.get("root_cause_category"):
            template_queries.append(f"{profile['root_cause_category']} mozilla")
        if profile.get("expected_code_roles"):
            template_queries.append(" ".join(profile["expected_code_roles"]))
        if profile.get("edit_operations"):
            template_queries.append(" ".join(profile["edit_operations"]))
        if profile.get("fix_pattern_category") and profile.get("expected_code_roles"):
            template_queries.append(f"{profile['fix_pattern_category']} {' '.join(profile['expected_code_roles'])}")
        if plan.get("root_cause_category") and plan.get("expected_edit_operations"):
            template_queries.append(f"{plan['root_cause_category']} {' '.join(plan['expected_edit_operations'])}")
        return self._dedupe_texts([*queries, *template_queries])

    def _find_line_matches(self, lines: Sequence[str], needle: str) -> List[int]:
        query = needle.strip()
        if not query:
            return []
        lowered_query = query.lower()
        fragments = [query]
        if "::" in query:
            fragments.append(query.split("::")[-1])
        fragments.extend(self._query_fragments(query)[:3])
        matched: List[int] = []
        for idx, line in enumerate(lines, start=1):
            lowered_line = line.lower()
            if any(fragment and fragment.lower() in lowered_line for fragment in fragments):
                matched.append(idx)
            if len(matched) >= 4:
                break
        if matched:
            return matched

        words = [word.lower() for word in WORD_RE.findall(lowered_query) if len(word) >= 5][:3]
        for idx, line in enumerate(lines, start=1):
            lowered_line = line.lower()
            if words and all(word in lowered_line for word in words[:2]):
                matched.append(idx)
            if len(matched) >= 2:
                break
        return matched

    def _reason_for_query(self, query: str, default_reason: str, match_type: str) -> str:
        if match_type == "analogical":
            return f"analogical match: {query}"
        return f"local match: {query}" if query else default_reason

    def _symbol_hint_from_query(self, query: str, path: str) -> str:
        symbols = SYMBOL_RE.findall(query)
        if symbols:
            return symbols[0].replace("(", "").replace(")", "")
        words = self._query_fragments(query)
        return words[0] if words else path.rsplit("/", 1)[-1]

    def _query_fragments(self, text: str) -> List[str]:
        words = [word for word in WORD_RE.findall(text) if len(word) >= 5]
        return self._dedupe_texts(words)[:4]

    def _dedupe_regions(self, regions: Sequence[RetrievedCodeRegion]) -> List[RetrievedCodeRegion]:
        deduped: List[RetrievedCodeRegion] = []
        seen = set()
        for region in regions:
            key = (region.path, region.start_line, region.end_line, region.match_type)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(region)
        return deduped

    def _heuristic_breakdown(
        self,
        *,
        candidate: RetrievedCodeRegion,
        plan: Dict[str, Any],
        profile: Dict[str, Any],
        context: Dict[str, Any],
        signals: RetrievalSignals,
        family_support: Dict[str, float],
    ) -> Dict[str, float]:
        bug_terms = self._term_set(
            context["bug"].get("title", ""),
            context["bug"].get("component", ""),
            context["bug"].get("product", ""),
            plan.get("problem_summary", ""),
        )
        path_terms = self._term_set(candidate.path)
        content_terms = self._term_set(candidate.content)
        symbol_terms = self._term_set(candidate.symbol, *signals.explicit_symbols, *plan.get("candidate_symbols", []))
        explicit_path_signal = 1.0 if candidate.path in set(signals.explicit_paths) else self._prefix_overlap(candidate.path, signals.explicit_paths)
        lexical_match = self._jaccard(bug_terms, path_terms | content_terms)
        symbol_overlap = self._jaccard(symbol_terms, path_terms | content_terms)
        query_support = min(1.0, len(candidate.query_support) / 4.0)

        fix_terms = self._term_set(
            plan.get("fix_pattern_category", ""),
            profile.get("fix_pattern_category", ""),
            *profile.get("edit_operations", []),
            *plan.get("expected_edit_operations", []),
        )
        root_terms = self._term_set(
            plan.get("root_cause_category", ""),
            profile.get("root_cause_category", ""),
            profile.get("bug_pattern", ""),
        )
        role_terms = self._term_set(*profile.get("expected_code_roles", []))
        fix_pattern_match = self._jaccard(fix_terms, content_terms | path_terms)
        root_cause_match = self._jaccard(root_terms, content_terms | path_terms)
        code_role_match = self._jaccard(role_terms, content_terms | path_terms)
        subsystem_compatibility = self._subsystem_prior(candidate.path, context, plan, profile)
        analogical_support = 1.0 if candidate.match_type == "analogical" else 0.25
        family_score = family_support.get(self._path_family(candidate.path), 0.0)
        code_hit_quality = self._code_hit_quality(candidate)

        scope_compatibility = 0.85 if candidate.match_type == "local" else 0.55
        if plan.get("expected_scope") == "broad_refactor":
            scope_compatibility = 0.65 if candidate.match_type == "local" else 0.8
        superficial_similarity_penalty = 0.0
        if candidate.match_type == "analogical" and lexical_match < 0.1 and symbol_overlap < 0.1:
            superficial_similarity_penalty = 0.45
        if candidate.match_type == "local" and explicit_path_signal == 0 and lexical_match < 0.08:
            superficial_similarity_penalty = max(superficial_similarity_penalty, 0.35)
        if "test" in candidate.path.lower() and "thread" not in context["bug"].get("title", "").lower():
            superficial_similarity_penalty = max(superficial_similarity_penalty, 0.2)
        superficial_similarity_penalty = max(
            superficial_similarity_penalty,
            self._superficial_trap_penalty(candidate.path, context, plan, profile),
        )

        return {
            "lexical_match": round(min(1.0, lexical_match + 0.10 * candidate.confidence), 4),
            "query_support": round(query_support, 4),
            "subsystem_compatibility": round(subsystem_compatibility, 4),
            "explicit_path_signal": round(explicit_path_signal, 4),
            "symbol_overlap": round(symbol_overlap, 4),
            "fix_pattern_match": round(fix_pattern_match, 4),
            "root_cause_match": round(root_cause_match, 4),
            "code_role_match": round(code_role_match, 4),
            "analogical_support": round(analogical_support, 4),
            "family_support": round(family_score, 4),
            "code_hit_quality": round(code_hit_quality, 4),
            "scope_compatibility": round(scope_compatibility, 4),
            "superficial_similarity_penalty": round(superficial_similarity_penalty, 4),
        }

    def _reason_labels(self, candidate: RetrievedCodeRegion, breakdown: Dict[str, float]) -> List[str]:
        labels = [candidate.match_type]
        if breakdown["query_support"] >= 0.5:
            labels.append("repeated_query_support")
        if breakdown["subsystem_compatibility"] >= 0.6:
            labels.append("subsystem_match")
        if breakdown["explicit_path_signal"] >= 0.5:
            labels.append("explicit_path_signal")
        if breakdown["symbol_overlap"] >= 0.2:
            labels.append("symbol_overlap")
        if breakdown["fix_pattern_match"] >= 0.15:
            labels.append("fix_pattern_match")
        if breakdown["root_cause_match"] >= 0.15:
            labels.append("root_cause_match")
        if breakdown["code_role_match"] >= 0.15:
            labels.append("code_role_match")
        if breakdown["family_support"] >= 0.5:
            labels.append("path_family_cluster")
        if breakdown["code_hit_quality"] >= 0.5:
            labels.append("code_hit_quality")
        if breakdown["superficial_similarity_penalty"] >= 0.3:
            labels.append("superficial_penalty")
        return self._dedupe_texts(labels)

    def _build_reason(self, candidate: RetrievedCodeRegion, breakdown: Dict[str, float], labels: Sequence[str]) -> str:
        parts = [candidate.retrieval_reason]
        if "repeated_query_support" in labels:
            parts.append("same path is supported by multiple independent queries")
        if "subsystem_match" in labels:
            parts.append("path matches expected subsystem")
        if "explicit_path_signal" in labels:
            parts.append("explicit path or prefix aligns with bug evidence")
        if "symbol_overlap" in labels:
            parts.append("same symbol or API vocabulary appears in region")
        if "fix_pattern_match" in labels:
            parts.append("edit pattern vocabulary matches expected fix shape")
        if "root_cause_match" in labels:
            parts.append("root-cause terminology overlaps with region")
        if "code_role_match" in labels:
            parts.append("region contains expected code roles")
        if "path_family_cluster" in labels:
            parts.append("directory family is reinforced by multiple candidates")
        if "code_hit_quality" in labels:
            parts.append("matches occur in executable code, not only comments")
        if "superficial_penalty" in labels:
            parts.append("penalized for mostly superficial similarity")
        return "; ".join(parts[:4])

    def _match_strength(self, score: float) -> str:
        if score >= 0.55:
            return "strong"
        if score >= 0.3:
            return "medium"
        return "weak"

    def _term_set(self, *values: str) -> set[str]:
        terms: set[str] = set()
        for value in values:
            for token in WORD_RE.findall(self._safe_text(value).lower()):
                if len(token) >= 4:
                    terms.add(token)
            for path in PATH_RE.findall(self._safe_text(value)):
                for part in re.split(r"[/._-]+", path.lower()):
                    if len(part) >= 3:
                        terms.add(part)
        return terms

    def _subsystem_prior(self, path: str, context: Dict[str, Any], plan: Dict[str, Any], profile: Dict[str, Any]) -> float:
        text = " ".join(
            [
                self._safe_text(context["bug"].get("title")),
                self._safe_text(context["bug"].get("component")),
                self._safe_text(context["bug"].get("product")),
                self._safe_text(plan.get("problem_summary")),
                self._safe_text(profile.get("bug_pattern")),
                self._safe_text(profile.get("root_cause_category")),
            ]
        ).lower()
        lowered_path = path.lower()
        positive_families: List[str] = []
        negative_families: List[str] = []

        if any(token in text for token in ["layout", "restyle", "style", ":hover", "selector", "node state"]):
            positive_families.extend(["layout/", "content/base/", "dom/", "content/"])
            negative_families.extend(["browser/", "toolkit/themes/", "webcompat/", "mail/"])
        if any(token in text for token in ["xpcom", "preference", "preferenceswriter", "libpref", "threadsanitizer", "data race"]):
            positive_families.extend(["modules/libpref/", "xpcom/", "mozglue/"])
            negative_families.extend(["browser/", "mail/", "toolkit/themes/"])
        if any(token in text for token in ["webextension", "extensions", "tabs", "permission", "origin"]):
            positive_families.extend(["toolkit/components/extensions/", "browser/components/extensions/"])
        if any(token in text for token in ["carddav", "addrbook", "address book"]):
            positive_families.extend(["mailnews/addrbook/", "mail/components/"])

        score = 0.35
        if any(lowered_path.startswith(prefix) for prefix in positive_families):
            score = 0.95
        elif positive_families:
            score = 0.2
        if any(lowered_path.startswith(prefix) for prefix in negative_families):
            score = min(score, 0.05)
        return score

    def _superficial_trap_penalty(self, path: str, context: Dict[str, Any], plan: Dict[str, Any], profile: Dict[str, Any]) -> float:
        text = " ".join(
            [
                self._safe_text(context["bug"].get("title")),
                self._safe_text(context["bug"].get("component")),
                self._safe_text(plan.get("problem_summary")),
                self._safe_text(profile.get("bug_pattern")),
            ]
        ).lower()
        lowered_path = path.lower()
        penalty = 0.0
        engine_bug = any(token in text for token in ["layout", "style", "restyle", ":hover", "node", "selector"])
        if engine_bug and any(token in lowered_path for token in ["browser/components/", "tab-hover-preview", "webcompat/", "toolkit/themes/"]):
            penalty = max(penalty, 0.6)
        if "webcompat/" in lowered_path:
            penalty = max(penalty, 0.5)
        if lowered_path.endswith(".css") and any(token in text for token in ["data race", "thread", "serialize", "registration"]):
            penalty = max(penalty, 0.45)
        return penalty

    def _family_support(self, candidates: Sequence[RetrievedCodeRegion]) -> Dict[str, float]:
        counts: Dict[str, int] = {}
        for candidate in candidates:
            family = self._path_family(candidate.path)
            counts[family] = counts.get(family, 0) + 1
        if not counts:
            return {}
        max_count = max(counts.values())
        return {family: count / max_count for family, count in counts.items()}

    def _path_family(self, path: str) -> str:
        parts = [part for part in path.split("/") if part]
        return "/".join(parts[:2]) + ("/" if len(parts) >= 2 else "")

    def _window_hit_quality(self, lines: Sequence[str], start: int, end: int, query: str) -> tuple[int, int]:
        code_hits = 0
        comment_hits = 0
        lowered_query = query.lower().strip()
        query_parts = [part.lower() for part in WORD_RE.findall(query) if len(part) >= 4][:3]
        for idx in range(start, end + 1):
            line = lines[idx - 1]
            lowered_line = line.lower()
            matched = lowered_query and lowered_query in lowered_line
            if not matched and query_parts:
                matched = any(part in lowered_line for part in query_parts)
            if not matched:
                continue
            stripped = line.strip()
            if stripped.startswith(("//", "/*", "*", "#")):
                comment_hits += 1
            else:
                code_hits += 1
        return code_hits, comment_hits

    def _code_hit_quality(self, candidate: RetrievedCodeRegion) -> float:
        total = candidate.code_hit_count + candidate.comment_hit_count
        if total <= 0:
            return 0.0
        return candidate.code_hit_count / total

    def _jaccard(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _prefix_overlap(self, path: str, explicit_paths: Sequence[str]) -> float:
        best = 0.0
        path_parts = [part for part in path.split("/") if part]
        for explicit in explicit_paths:
            explicit_parts = [part for part in explicit.split("/") if part]
            overlap = 0
            for left, right in zip(path_parts, explicit_parts):
                if left != right:
                    break
                overlap += 1
            if explicit_parts:
                best = max(best, overlap / len(explicit_parts))
        return round(best, 4)

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

    @staticmethod
    def _normalize_list(value: Any, *, limit: int) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:limit]

    @staticmethod
    def _normalize_paths(value: Any, *, limit: int) -> List[str]:
        items = TraceFixAgent._normalize_list(value, limit=limit * 2)
        paths: List[str] = []
        for item in items:
            match = PATH_RE.search(item)
            if match:
                paths.append(match.group(0))
            elif "/" in item and "." in item.rsplit("/", 1)[-1]:
                paths.append(item.strip())
        return TraceFixAgent._dedupe_paths(paths)[:limit]

    @staticmethod
    def _dedupe_paths(paths: Sequence[str]) -> List[str]:
        deduped: List[str] = []
        seen = set()
        for path in paths:
            value = path.strip().lstrip("/")
            if not value or value in seen or "::" in value or "(" in value:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    @staticmethod
    def _dedupe_texts(values: Sequence[str]) -> List[str]:
        deduped: List[str] = []
        seen = set()
        for value in values:
            text = value.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    @staticmethod
    def _safe_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value)
