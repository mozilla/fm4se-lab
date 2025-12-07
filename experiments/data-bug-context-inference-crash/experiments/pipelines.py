from __future__ import annotations

from typing import Dict, Optional, Any

from crewai import Crew, Process

from .bugzilla import fetch_bug, fetch_bug_comments, build_bug_text
from .phabricator import fetch_raw_diff
from .diff_utils import get_original_snippets_for_revision
from .context_builders import (
    build_bug_and_code_context,build_crash_add_context
)
from .agents import (
    make_missing_info_to_reach_patch_agent,
    make_missing_info_simulator_agent,
    make_crash_report_filter_agent,
    make_missing_info_bug_only_agent,
    make_patch_filter_agent,
    make_patch_synthesis_agent,
)
from .tasks import (
    make_missing_info_to_reach_patch_task,
    make_missing_info_simulation_task,
    make_missing_info_after_sim_task,
    make_crash_report_filter_task,
    make_missing_info_bug_only_task,
    make_patch_filter_task,
    make_patch_synthesis_task,
)


# ============================================================
# Orchestrator: original pipeline + crash report filtering
# ============================================================

def run_missing_info_to_reach_patch_pipeline(
    bug_id: int,
    revision_id: int,
    patch_id: Optional[int] = None,
) -> Dict[str, str]:
    bug = fetch_bug(bug_id)
    comments = fetch_bug_comments(bug_id)
    bug_text = build_bug_text(bug, comments=comments)

    patch_diff = fetch_raw_diff(revision_id, patch_id=patch_id)

    # Analyze missing info to reach the patch, simulate additional info,
    agent_missing = make_missing_info_to_reach_patch_agent()
    task_missing = make_missing_info_to_reach_patch_task(
        bug_text=bug_text,
        patch_diff=patch_diff,
        agent=agent_missing,
    )

    crew_missing = Crew(
        agents=[agent_missing],
        tasks=[task_missing],
        process=Process.sequential,
        verbose=False,
    )
    missing_info_output = str(crew_missing.kickoff())

    # Simulate additional info to help reach the patch
    simulator_agent = make_missing_info_simulator_agent()
    simulator_task = make_missing_info_simulation_task(
        bug_text=bug_text,
        patch_diff=patch_diff,
        missing_info_analysis=missing_info_output,
        agent=simulator_agent,
    )

    crew_simulator = Crew(
        agents=[simulator_agent],
        tasks=[simulator_task],
        process=Process.sequential,
        verbose=False,
    )
    simulated_info_output = str(crew_simulator.kickoff())

    # Check missing info again after adding simulated info
    task_missing_after_sim = make_missing_info_after_sim_task(
        original_bug_text=bug_text,
        patch_diff=patch_diff,
        simulated_info=simulated_info_output,
        agent=agent_missing,
    )

    crew_missing_after_sim = Crew(
        agents=[agent_missing],
        tasks=[task_missing_after_sim],
        process=Process.sequential,
        verbose=False,
    )
    missing_info_after_sim_output = str(crew_missing_after_sim.kickoff())
    full_context_after_sim = build_crash_add_context(
        bug_text, simulated_info_output
    )

    # Filter crash report to focus on the patch
    filter_agent = make_crash_report_filter_agent()
    filter_task = make_crash_report_filter_task(
        original_bug_text=bug_text,
        simulated_additional_info=simulated_info_output,
        patch_diff=patch_diff,
        agent=filter_agent,
    )
    crew_filter = Crew(
        agents=[filter_agent],
        tasks=[filter_task],
        process=Process.sequential,
        verbose=False,
    )
    filtered_crash_report_output = str(crew_filter.kickoff())

    return {
        "bug_text": bug_text,
        "patch_diff": patch_diff,
        "missing_info_analysis_initial": missing_info_output,
        "simulated_additional_info": simulated_info_output,
        "missing_info_analysis_after_simulation": missing_info_after_sim_output,
        "full_context_after_simulation": full_context_after_sim,
        "filtered_crash_report_for_patch": filtered_crash_report_output,
    }


# ============================================================
# Experimental 1: bug-only -> filtered by patch
# ============================================================

def run_missing_info_two_stage_pipeline(
    bug_id: int,
    revision_id: int,
    patch_id: Optional[int] = None,
) -> Dict[str, str]:
    bug = fetch_bug(bug_id)
    comments = fetch_bug_comments(bug_id)
    bug_text = build_bug_text(bug, comments=comments)

    patch_diff = fetch_raw_diff(revision_id, patch_id=patch_id)

    bug_only_agent = make_missing_info_bug_only_agent()
    bug_only_task = make_missing_info_bug_only_task(
        bug_text=bug_text,
        agent=bug_only_agent,
    )
    crew_bug_only = Crew(
        agents=[bug_only_agent],
        tasks=[bug_only_task],
        process=Process.sequential,
        verbose=False,
    )
    missing_info_bug_only_output = str(crew_bug_only.kickoff())

    patch_filter_agent = make_patch_filter_agent()
    patch_filter_task = make_patch_filter_task(
        bug_text=bug_text,
        patch_diff=patch_diff,
        bug_only_missing_info=missing_info_bug_only_output,
        agent=patch_filter_agent,
    )
    crew_patch_filter = Crew(
        agents=[patch_filter_agent],
        tasks=[patch_filter_task],
        process=Process.sequential,
        verbose=False,
    )
    missing_info_filtered_output = str(crew_patch_filter.kickoff())

    simulator_agent = make_missing_info_simulator_agent()
    simulator_task = make_missing_info_simulation_task(
        bug_text=bug_text,
        patch_diff=patch_diff,
        missing_info_analysis=missing_info_filtered_output,
        agent=simulator_agent,
    )
    crew_simulator = Crew(
        agents=[simulator_agent],
        tasks=[simulator_task],
        process=Process.sequential,
        verbose=False,
    )
    simulated_info_output = str(crew_simulator.kickoff())

    agent_missing_after = make_missing_info_to_reach_patch_agent()
    task_missing_after_sim = make_missing_info_after_sim_task(
        original_bug_text=bug_text,
        patch_diff=patch_diff,
        simulated_info=simulated_info_output,
        agent=agent_missing_after,
    )
    crew_missing_after_sim = Crew(
        agents=[agent_missing_after],
        tasks=[task_missing_after_sim],
        process=Process.sequential,
        verbose=False,
    )
    missing_info_after_sim_output = str(crew_missing_after_sim.kickoff())

    return {
        "bug_text": bug_text,
        "patch_diff": patch_diff,
        "missing_info_bug_only": missing_info_bug_only_output,
        "missing_info_filtered_for_patch": missing_info_filtered_output,
        "simulated_additional_info": simulated_info_output,
        "missing_info_analysis_after_simulation": missing_info_after_sim_output,
    }


# ============================================================
# Experimental 2: crash report (filtered or not) + original code -> patch
# ============================================================

def run_patch_synthesis_mode(
    bug_id: int,
    revision_id: int,
    patch_id: Optional[int] = None,
    additional_info: Optional[str] = None,
    crash_report_override: Optional[str] = None,
) -> Dict[str, Any]:
    # Use either the filtered crash report override, or fetch from Bugzilla
    if crash_report_override is not None:
        bug_text = crash_report_override
    else:
        bug = fetch_bug(bug_id)
        comments = fetch_bug_comments(bug_id)
        bug_text = build_bug_text(bug, comments=comments)

    original_snippets = get_original_snippets_for_revision(revision_id, patch_id=patch_id)

    bug_and_code_context = build_bug_and_code_context(
        bug_text,
        original_snippets,
        additional_info=additional_info,
    )

    # print("=== Bug and Code Context for Patch Synthesis ===")
    # print(bug_and_code_context)
    patch_agent = make_patch_synthesis_agent()
    patch_task = make_patch_synthesis_task(bug_and_code_context, patch_agent)

    crew_patch = Crew(
        agents=[patch_agent],
        tasks=[patch_task],
        process=Process.sequential,
        verbose=False,
    )
    patch_proposal_output = str(crew_patch.kickoff())

    return {
        "crash_report_used": bug_text,
        "original_code_snippets": original_snippets,
        "patch_proposal": patch_proposal_output,
        "additional_info_used": additional_info,
    }
