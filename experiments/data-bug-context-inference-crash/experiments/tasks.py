from __future__ import annotations

from typing import Dict, Optional

from crewai import Task, Crew, Process

from .agents import build_gemini_agent
from .context_builders import (
    build_crash_and_patch_context,
    build_crash_add_and_patch_context,
)


# ============================================================
# Tasks: missing info to reach patch
# ============================================================

def make_missing_info_to_reach_patch_task(
    bug_text: str,
    patch_diff: str,
    agent,
) -> Task:
    context = build_crash_and_patch_context(bug_text, patch_diff)

    return Task(
        agent=agent,
        description=f"""
You are analysing a Firefox crash and a proposed fix patch.

You are given the following context:

--- CONTEXT BEGIN ---
{context}
--- CONTEXT END ---

- The first part is the **crash report** (Bugzilla, including comments).
- The second part is the **patch diff** (Phabricator), which is a *candidate fix*.

Your job is NOT to re-describe the bug or the patch, but to answer this question:

> What information is missing in the crash report that would help an engineer
> understand, justify, and confidently arrive at this specific patch as the fix?

Be very concrete and specific.

Very important constraints:
- Only list information that is truly **missing** and would materially help justify THIS patch.
- Do NOT repeat or paraphrase information that is already in the crash report.
- Do NOT invent extra categories of missing info just to fill space.
- If you judge that no additional information is strictly needed, say so explicitly
  instead of making up missing items.

Output format:

- Missing information in the crash report to reach/justify the patch:
  - <missing information item 1> (and why this helps justify the patch)
  - <missing information item 2> (...)
  - If nothing important is missing, write:
    - (No additional information is required; the crash report already contains
       enough detail to understand and justify the patch.)
""",
        expected_output=(
            "A bullet list under the heading "
            "'- Missing information in the crash report to reach/justify the patch:' "
            "where each bullet explains why the missing info would help an "
            "engineer understand and justify this patch as the fix, or a single "
            "bullet explicitly stating that no additional information is required."
        ),
    )


def plan_missing_info_retrieval_tool(
    bug_text: str,
    patch_diff: str,
    missing_info_analysis: str,
) -> str:
    """
    LLM helper : plan de récupération des infos manquantes.
    """
    context = build_crash_and_patch_context(bug_text, patch_diff)

    retrieval_agent = build_gemini_agent(
        name="MissingInfoRetrievalPlanner",
        role="Crash Investigation & Data Collection Planner",
        goal=(
            "Given a crash report, a patch, and a list of missing information, "
            "produce a practical plan describing what data to collect and how "
            "to collect it in order to fill the missing items and validate the patch."
        ),
        backstory=(
            "You are an experienced crash investigator. You know which "
            "additional logs, reproduction details, environment info, "
            "test plans, and code insights are required to fill the gaps "
            "in a crash report and to confidently fix and validate a patch."
        ),
        model="deepseek-reasoner",
        temperature=0.7,
    )

    retrieval_task = Task(
        agent=retrieval_agent,
        description=f"""
You are planning a crash investigation and data collection strategy
for a Firefox crash and a proposed fix patch.

You have the following crash + patch context:

--- CONTEXT (CRASH REPORT + PATCH) BEGIN ---
{context}
--- CONTEXT (CRASH REPORT + PATCH) END ---

And the following analysis of missing information in the crash report:

--- MISSING INFORMATION ANALYSIS BEGIN ---
{missing_info_analysis}
--- MISSING INFORMATION ANALYSIS END ---

For each missing information item, describe:
- what concrete data should be obtained,
- *how* to obtain it,
- how it helps confirm that the proposed patch is correct.

Very important constraints:
- Only plan retrieval for the missing information items explicitly listed above.
- Do NOT invent new missing items that are not in the analysis.
- Be concise and practical: no long prose, no extra commentary.

Output format:

- Retrieval plan for missing information:
  - <missing info item 1>:
    - Data to collect: ...
    - How to collect it: ...
    - Why this validates the patch: ...
  - <missing info item 2>:
    ...
- If nothing substantial is missing, write:
    - (No additional information is required; with the additional crash
       information, the report now contains enough detail to understand
       and justify the patch.)
""",
        expected_output=(
            "A structured plan under the heading "
            "'- Retrieval plan for missing information:' "
            "listing, for each missing information item, what data is needed "
            "and how to collect it, without additional unrelated content."
        ),
    )

    crew_retrieval = Crew(
        agents=[retrieval_agent],
        tasks=[retrieval_task],
        process=Process.sequential,
        verbose=False,
    )

    result = crew_retrieval.kickoff()
    return str(result)


# ============================================================
# Tasks: simulation, second-pass, filtering
# ============================================================

def make_missing_info_simulation_task(
    bug_text: str,
    patch_diff: str,
    missing_info_analysis: str,
    agent,
) -> Task:
    context = build_crash_and_patch_context(bug_text, patch_diff)

    return Task(
        agent=agent,
        description=f"""
You are given:

--- CONTEXT (CRASH REPORT + PATCH) BEGIN ---
{context}
--- CONTEXT (CRASH REPORT + PATCH) END ---

And the following analysis of missing information in the crash report:

--- MISSING INFORMATION ANALYSIS BEGIN ---
{missing_info_analysis}
--- MISSING INFORMATION ANALYSIS END ---

Your job is to **simulate** (invent) realistic and internally consistent
values for these missing items, as if the original reporter had provided
a perfect, detailed crash report.

Rules:
- Only simulate information that directly corresponds to the missing items
  listed in the analysis above. Do NOT add extra categories or unrelated details.
- Be explicit and concrete but still concise.
- Keep everything *plausible* with respect to the patch and the crash context.
- Clearly label that this is **simulated information**, not from the original reporter.
- If the missing information analysis states that no additional information
  is required, then say so and DO NOT invent any simulated information.

Output format:

- Additional crash information:
  - <simulated detail for missing item 1>
  - <simulated detail for missing item 2>
  - ...
  - If no simulation is needed, write:
    - (No simulated information; the crash report is already sufficient.)
""",
        expected_output=(
            "A bullet list under the heading "
            "'- Additional crash information :' "
            "containing plausible concrete details for each missing item, or a single bullet "
            "stating that no simulated information is needed."
        ),
    )


def make_missing_info_after_sim_task(
    original_bug_text: str,
    patch_diff: str,
    simulated_info: str,
    agent,
) -> Task:
    context = build_crash_add_and_patch_context(original_bug_text, simulated_info, patch_diff)

    return Task(
        agent=agent,
        description=f"""
        You are analysing a Firefox crash and a proposed fix patch.

        You are given the following context:

        --- CONTEXT BEGIN ---
        {context}
        --- CONTEXT END ---

        The context may contain up to three logical parts, in this order:
        1) The original crash report (Bugzilla, including comments).
        2) An "ADDITIONAL CRASH INFORMATION" section: this represents extra
        information that we imagine was added to the crash report
        (you MUST treat this as if it were now part of the crash report).
        3) The patch diff (Phabricator), which is a candidate fix.

        Your job is NOT to re-describe the bug or the patch, but to answer this question:

        > Based on the crash report PLUS any "ADDITIONAL CRASH INFORMATION" present,
        > what information is still missing that would help an engineer understand,
        > justify, and confidently arrive at THIS specific patch as the fix?

        Be very concrete and specific.

        Very important constraints:
        - Treat the "ADDITIONAL CRASH INFORMATION" section as if it were now included
        in the crash report. Do NOT ignore it.
        - Only list information that is truly missing and would materially help justify THIS patch.
        - Do NOT repeat or paraphrase information that is already in the crash report,
        the additional crash information, or the patch.
        - Do NOT invent extra categories of missing info just to fill space.
        - If you judge that no additional information is strictly needed, say so explicitly
        instead of making up missing items.

        Output format:

        - Missing information in the crash report information to reach/justify the patch:
        - <missing information item 1> (and why this helps justify the patch)
        - <missing information item 2> (...)
        - If nothing important is missing, write:
            - (No additional information is required; the crash report already contains
            enough detail to understand and justify the patch.)
        """,
        expected_output=(
            "A bullet list under the heading "
            "'- Missing information in the crash report information to reach/justify the patch:' "
            "where each bullet explains why the missing info would help an engineer understand "
            "and justify this patch as the fix, or a single bullet explicitly stating that no "
            "additional information is required."
        ),
    )


# def make_crash_report_filter_task(
#     original_bug_text: str,
#     simulated_additional_info: str,
#     patch_diff: str,
#     agent,
# ) -> Task:
#     context = build_crash_add_and_patch_context(original_bug_text, simulated_additional_info, patch_diff)

#     return Task(
#         agent=agent,
#         description=f"""
# You are given:

# --- CONTEXT (CRASH REPORT + ADDITIONAL INFO + PATCH) BEGIN ---
# {context}
# --- CONTEXT (CRASH REPORT + ADDITIONAL INFO + PATCH) END ---

# The context has:
# 1) The original crash report (Bugzilla, including comments).
# 2) An "ADDITIONAL CRASH INFORMATION" section with simulated but plausible details.
# 3) The patch diff, which is the candidate fix.

# Your job:

# > Rewrite the crash report into a **concise, self-contained crash report**
# > that includes ONLY the information that is necessary or very helpful
# > to confidently arrive at THIS patch as the fix.

# Very important constraints:
# - Treat the ADDITIONAL CRASH INFORMATION as if it were really part of the report.
# - Use the patch diff ONLY as a lens to decide which crash details matter.
# - The **output MUST NOT** contain any patch code or diff; it is a crash report,
#   not a code review.
# - Remove noisy informations.
# - If some original details are unnecessary to motivate this patch, drop them.
# - Keep the report well-structured and readable.

# Do not add new information that is not implied by the input.
# If something is unknown, just omit it instead of inventing it.
# """,
#         expected_output=(
#             "A short, well-structured markdown crash report containing only the "
#             "information truly needed coming from the context to arrive to the patch."
#         ),
#     )


def make_crash_report_filter_task(
    original_bug_text: str,
    simulated_additional_info: str,
    patch_diff: str,
    agent,
) -> Task:
    context = build_crash_add_and_patch_context(
        original_bug_text,
        simulated_additional_info,
        patch_diff,
    )

    return Task(
        agent=agent,
        description=f"""
You are given a single block of technical context that contains:
- a Firefox crash report from Bugzilla (including comments),
- some extra crash-related details that could plausibly have been part of the report,
- and a patch diff that fixes the crash.

--- FULL CONTEXT BEGIN ---
{context}
--- FULL CONTEXT END ---

Your job:

Rewrite this into a **concise, self-contained crash report** that keeps
only the information that is truly useful to:

- understand what crash is happening,
- understand under which conditions it happens,
- and make the fix implemented by the given patch feel natural and well-motivated.

How you should think about it:

- Read everything (bug, comments, extra crash information, and patch diff).
- Use the patch **only as a lens** to decide which crash-related details matter.
- For each piece of information in the context, ask yourself:
  "Does this concretely help an engineer understand or localize the problem
   in a way that supports this particular fix?"
- KEEP it if the answer is yes.
- DROP it if it is noise, off-topic, redundant, or not needed to justify this fix.

Very important constraints:

- The output must look like a normal crash report, not a patch explanation.
- The output MUST NOT contain any patch code, diff fragments, or function bodies.
- The output MUST NOT mention that a patch exists, or that you used it.
- Do not add new information; only use what is already implied by the context.
- If some original details are not necessary to motivate this fix, just omit them.
- Keep the result well-structured and readable (you may use markdown headings and bullets).

Do not explain your reasoning. Do not comment on what you removed.
Only output the rewritten crash report.
""",
        expected_output=(
            "A short, well-structured markdown crash report containing only the "
            "crash-related information from the context that is genuinely needed "
            "to understand the crash and naturally motivate the specific fix in "
            "the patch, without including any code or mentioning the patch."
        ),
    )

# ============================================================
# Bug-only, patch-filtering tasks
# ============================================================

def make_missing_info_bug_only_task(
    bug_text: str,
    agent,
) -> Task:
    return Task(
        agent=agent,
        description=f"""
You are analysing a Firefox crash report (Bugzilla, including comments).

You are given the following crash context:

--- CRASH REPORT (Bugzilla) BEGIN ---
{bug_text}
--- CRASH REPORT (Bugzilla) END ---

Your job is NOT to propose a fix or talk about patches (you do not see any patch).
Instead, answer this question:

> What information is missing in the crash report that would help an engineer
> understand, investigate, and reproduce the crash effectively?

Be very concrete and specific.

Very important constraints:
- Only list information that is truly missing and would materially help a crash investigation.
- Do NOT repeat or paraphrase information that is already in the crash report.
- Do NOT speculate about any patch or fix (you don't see any patch).
- If you judge that no additional information is strictly needed, say so explicitly
  instead of making up missing items.

Output format:

- Missing information in the crash report (patch-agnostic):
  - <missing information item 1> (and why this helps investigate the crash)
  - <missing information item 2> (...)
  - If nothing important is missing, write:
    - (No additional information is required; the crash report already contains
       enough detail to investigate the crash.)
""",
        expected_output=(
            "A bullet list under the heading "
            "'- Missing information in the crash report (patch-agnostic):' "
            "where each bullet explains why the missing info would help an "
            "engineer investigate the crash, or a single bullet explicitly "
            "stating that no additional information is required."
        ),
    )


def make_patch_filter_task(
    bug_text: str,
    patch_diff: str,
    bug_only_missing_info: str,
    agent,
) -> Task:
    context = build_crash_and_patch_context(bug_text, patch_diff)

    return Task(
        agent=agent,
        description=f"""
You are given:

--- CONTEXT (CRASH REPORT + PATCH) BEGIN ---
{context}
--- CONTEXT (CRASH REPORT + PATCH) END ---

And the following analysis of missing information in the crash report,
produced WITHOUT knowing the patch:

--- PATCH-AGNOSTIC MISSING INFORMATION BEGIN ---
{bug_only_missing_info}
--- PATCH-AGNOSTIC MISSING INFORMATION END ---

Your job is to filter this list to keep ONLY the items that are important
to understand, justify, and confidently arrive at THIS specific patch as the fix.

Rules:
- Do NOT invent new missing items that are not in the patch-agnostic list.
- You may rephrase or merge items for clarity, but do not add new content.
- If an item is not useful for justifying THIS patch, drop it.
- If nothing from the patch-agnostic list is needed to justify the patch,
  say so explicitly.

Output format:

- Missing information in the crash report to reach/justify the patch (filtered):
  - <filtered missing information item 1> (and why this helps justify the patch)
  - <filtered missing information item 2> (...)
  - If no item is actually required to justify this patch, write:
    - (No additional information is required; the crash report already contains
       enough detail to understand and justify the patch.)
""",
        expected_output=(
            "A bullet list under the heading "
            "'- Missing information in the crash report to reach/justify the patch (filtered):' "
            "containing only the subset of patch-relevant missing items, or a single bullet "
            "stating that no additional information is required."
        ),
    )


# ============================================================
# Patch synthesis task
# ============================================================

def make_patch_synthesis_task(
    bug_and_code_context: str,
    agent,
) -> Task:
    return Task(
        agent=agent,
        description=f"""
        You are given a Firefox crash report (already focused on the information
        needed to reach a given patch) and the ORIGINAL (pre-patch) code for the
        files that are involved in the fix.

        The context includes:
        - The filtered crash report focused on reaching the patch.
        - Optionally, an "ADDITIONAL CRASH INFORMATION" section.
        - The original code from the diff (pre-patch).

        --- CONTEXT (CRASH REPORT + OPTIONAL ADDITIONAL INFO + ORIGINAL CODE) BEGIN ---
        {bug_and_code_context}
        --- CONTEXT (CRASH REPORT + OPTIONAL ADDITIONAL INFO + ORIGINAL CODE) END ---

        Your job is to propose a concrete patch that would plausibly fix the crash.
        You must use the crash context to justify why your patch prevents this
        specific crash in the scenario described.

        Very important constraints:
        - Base your changes ONLY on the ORIGINAL code shown above.
        - Make the smallest reasonable change that fixes the problem.
        - Prefer to keep the existing style and structure of the code.
        - Do NOT invent new files or large rewrites unless absolutely necessary.

           - A patch in unified diff style, based on the original code shown above.
        - Make sure to use correct diff syntax with @@ hunk headers.
        - Only include changes to the original code shown above.
        - If you are unsure about exact syntax, do your best to approximate it.

        If you are unsure, still propose the most reasonable patch you can,
        but do not write long essays outside the requested sections.
        """,
        expected_output=(
            "A unified diff-style patch that "
            "modifies only the original code shown in the context."
        ),
    )
