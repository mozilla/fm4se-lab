from __future__ import annotations

from typing import Optional

from crewai import Agent, LLM

from .config import DEEPSEEK_API_KEY, DEFAULT_MODEL


def _build_llm(
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    api_key: Optional[str] = None,
) -> LLM:
    """
    Create an LLM instance pointing to DeepSeek's API.
    """
    key = api_key or DEEPSEEK_API_KEY
    if not key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY environment variable is not set."
        )

    return LLM(
        model=model,
        api_key=key,
        base_url="https://api.deepseek.com/v1",
        temperature=temperature,
    )


def build_gemini_agent(  # keeping original name for minimal diff
    name: str,
    role: str,
    goal: str,
    backstory: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
) -> Agent:
    llm = _build_llm(model=model, temperature=temperature)

    return Agent(
        name=name,
        role=role,
        goal=goal
        + " Always be concise and only provide information that is strictly necessary. "
          "If nothing is missing or nothing needs to be added, state that clearly and do not invent extra content.",
        backstory=backstory,
        llm=llm,
        tools=[],
        allow_delegation=False,
        verbose=False,
    )


# ============================================================
# Agent factories
# ============================================================

def make_missing_info_to_reach_patch_agent() -> Agent:
    return build_gemini_agent(
        name="MissingInfoToReachPatchAnalyst",
        role="Crash Report Gap Analyst (Patch-Oriented)",
        goal=(
            "Given a crash report and a proposed fix patch, identify which "
            "information is missing in the crash report that would help an "
            "engineer understand, justify, and confidently arrive at this "
            "specific patch as the fix."
        ),
        backstory=(
            "You are a senior Firefox crash engineer and reviewer. "
            "You are used to reading Bugzilla reports and Phabricator patches, "
            "and you know what information should be in the crash report so "
            "that the path towards a given patch is clear, justified, and testable."
        ),
        temperature=0.7,
    )


def make_missing_info_simulator_agent() -> Agent:
    return build_gemini_agent(
        name="MissingInfoSimulator",
        role="Crash Context Completion Agent",
        goal=(
            "Given a crash report, a patch, and a list of missing information, "
            "invent realistic and internally consistent values for ONLY those "
            "missing information items, as if an ideal reporter had provided them."
        ),
        backstory=(
            "You are an experienced Firefox engineer with deep intuition for typical "
            "crash conditions and environments. You can fabricate plausible details "
            "that would reasonably appear in a well-written crash report."
        ),
        temperature=0.7,
    )


def make_crash_report_filter_agent() -> Agent:
    return build_gemini_agent(
        name="CrashReportFilterForPatch",
        role="Crash Report Condenser (Patch-Oriented)",
        goal=(
            "Given a full crash report, additional crash information, and the patch diff, "
            "rewrite the crash report into a concise, self-contained report that contains "
            "only the information that is strictly necessary to understand, justify, and "
            "arrive at THIS specific patch as the fix."
        ),
        backstory=(
            "You are a senior Firefox triager. You know how to strip away noise from "
            "Bugzilla reports and keep just the details that are essential to motivate "
            "and justify a particular patch."
        ),
        temperature=0.4,
    )


def make_missing_info_bug_only_agent() -> Agent:
    return build_gemini_agent(
        name="BugOnlyMissingInfoAnalyst",
        role="Crash Report Gap Analyst (Patch-Agnostic)",
        goal=(
            "Given a crash report (without any patch), identify which "
            "information is missing that would help an engineer understand "
            "and investigate the crash effectively."
        ),
        backstory=(
            "You are a senior Firefox crash engineer. You are used to reading "
            "Bugzilla reports and you know what information should be present "
            "for a good investigation, regardless of any specific fix patch."
        ),
        temperature=0.7,
    )


def make_patch_filter_agent() -> Agent:
    return build_gemini_agent(
        name="PatchOrientedMissingInfoFilter",
        role="Patch-Oriented Crash Gap Filter",
        goal=(
            "Given a crash report, a patch diff, and a generic list of missing "
            "information from the crash report, select and rephrase only the "
            "items that are important to understand, justify, and confidently "
            "arrive at THIS specific patch as the fix."
        ),
        backstory=(
            "You are an experienced Firefox engineer reviewing both crash reports "
            "and patches. You know which crash details are actually necessary "
            "to justify a given patch, and which are just nice-to-have."
        ),
        temperature=0.7,
    )


def make_patch_synthesis_agent() -> Agent:
    return build_gemini_agent(
        name="PatchSynthesisAgent",
        role="Crash Fix Patch Synthesis Agent",
        goal=(
            "Given a detailed crash report and the original (pre-patch) code "
            "snippets for the files involved, propose a concrete patch that "
            "would plausibly fix the crash."
        ),
        backstory=(
            "You are a senior Firefox C++/Rust engineer used to writing small, "
            "targeted patches for crash bugs. You think about correctness, "
            "thread-safety, and minimal changes."
        ),
        temperature=0.4,
    )
