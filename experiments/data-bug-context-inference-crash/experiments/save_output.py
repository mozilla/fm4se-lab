import json

def save_as_json(result, patch_result, bug_id=None):
    payload = {
        "result": {
            "original_patch": result.get("patch_diff"),
            "missing_info_analysis_initial": result.get("missing_info_analysis_initial"),
            "simulated_additional_info": result.get("simulated_additional_info"),
            "missing_info_analysis_after_simulation": result.get("missing_info_analysis_after_simulation"),
            "filtered_crash_report_for_patch": result.get("filtered_crash_report_for_patch"),
            "patch_proposal": patch_result.get("patch_proposal"),
        },
        "patch_result": patch_result,
    }


    out_path = f"results/synthesis_output_bug_{bug_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    print(f"Saved output to {out_path}")
