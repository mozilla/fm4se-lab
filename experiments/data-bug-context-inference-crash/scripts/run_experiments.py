from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1] 


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from experiments.pipelines import (
    run_missing_info_to_reach_patch_pipeline,
    run_patch_synthesis_mode,
)


def main() -> None:
    experiments = [
        (1998653, 271608, None),
        # (1997854, 271086, None),
        # (1965607, 248723, None),
        # ...
    ]

    for bug_id, revision_id, patch_id in experiments:
        try:
            print(
                f"\n=== Analyse bug {bug_id} / D{revision_id}: "
                "Missing information to reach/justify the patch (pipeline original) ==="
            )

            # 1- Original pipeline: missing info + simulation + filtered crash report
            result = run_missing_info_to_reach_patch_pipeline(
                bug_id=bug_id,
                revision_id=revision_id,
                patch_id=patch_id,
            )

            print("\n--- Initial missing information to reach/justify the patch ---")
            print(result["missing_info_analysis_initial"])

            print("\n--- Simulated additional crash information ---")
            print(result["simulated_additional_info"])

            print("\n--- Missing information after adding simulated info ---")
            print(result["missing_info_analysis_after_simulation"])

            # print("\n--- Full crash report + simulated info context ---")
            # print(result["full_context_after_simulation"])

            print("\n--- Filtered crash report focused on this patch ---")
            print(result["filtered_crash_report_for_patch"])

            # 2- Generate patch proposal from filtered crash report
            patch_result = run_patch_synthesis_mode(
                bug_id=bug_id,
                revision_id=revision_id,
                patch_id=patch_id,
                additional_info=None, 
                crash_report_override=result["filtered_crash_report_for_patch"],
            )

            print("\n--- [PATCH] Proposed patch ---")
            print(patch_result["patch_proposal"])

        except Exception as e:
            print(f"Error during processing bug {bug_id} / D{revision_id}:", e)


if __name__ == "__main__":
    main()
