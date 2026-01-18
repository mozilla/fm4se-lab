# Data Bug Context Inference - Non Crash Bugs

A comprehensive system for creating detailed bug reports and automated program repair datasets from Mozilla's Bugzilla, Phabricator, and related infrastructure.

## Overview

This tool automatically collects, analyzes, and synthesizes bug information from multiple Mozilla data sources to create rich datasets suitable for:
- Automated Program Repair (APR) research
- Bug triaging and analysis
- Code review quality assessment
- Software engineering research
- LLM training for code generation and debugging

## Features

### Multi-Source Data Collection
- **Bugzilla**: Bug reports, comments, history, attachments
- **Phabricator**: Code reviews (differentials), patches, reviewer feedback
- **Mercurial (hg.mozilla.org)**: Commit data and history
- **Searchfox**: Source code context and cross-references

### LLM-Powered Analysis
- Root cause identification
- Impact assessment
- Fix quality metrics
- Comprehensive technical summaries
- **Zero-shot fix generation** (for APR research)

### Structured Output
- JSON metadata for machine learning
- Raw unified diffs for patch analysis
- Human-readable comprehensive reports
- Generated fixes for comparison

## Installation

### Prerequisites
- Python 3.8+
- Google Gemini API key

### Setup
1. Clone the repository and install in editable mode:
```bash
git clone <your-repo-url>
cd mozilla-bug-analyzer
pip install -e .
```

2. Create a `.env` file:
```bash
echo "GOOGLE_API_KEY=your_gemini_api_key_here" > .env
```

## Usage

### Interactive Mode
Run the interactive agent to analyze a single bug:
```bash
# Using the installed entry point
analyze-bug

# OR running the script directly
python scripts/analyze_bug.py
```
Enter a Bugzilla ID (e.g., `2001809`) when prompted.

### Batch Automation
Run the batch processor to handle multiple bugs without supervision. This script includes **automatic rate limiting** (default: 60s delay).
```bash
# Process specific bugs
python scripts/run_batch.py --bug_ids 2001809 1234567

# Process from a file (one ID per line)
python scripts/run_batch.py --file bug_list.txt

# Adjust delay (e.g., 90 seconds)
python scripts/run_batch.py --file bug_list.txt --delay 90
```

### Programmatic Usage
```python
from mozilla_bug_analyzer.analyzer import ComprehensiveBugAnalyzer

analyzer = ComprehensiveBugAnalyzer(gemini_api_key="your_key")
report = analyzer.create_comprehensive_bug_report(2001809)
```

## Agentic Capabilities

### Iterative Refinement Loop
The agent now employs an **iterative refinement loop** (up to 3 rounds) before generating a fix.
1.  **Critique**: The LLM critiques its own analysis against a research-backed checklist (arXiv:2512.21426).
2.  **Active Fetching**: If data is missing (e.g., specific file contents), the agent **autonomously requests** to:
    *   Read files from `hg.mozilla.org`.
    *   Search for code definitions using `Searchfox`.
3.  **Versioning**: Every refinement iteration is saved as a separate JSON file (`bug_ID_analysis_v1.json`, etc.) for auditability.

## Output Structure
```
mozilla_bug_dataset/
├── json_data/
│   └── bug_2001809.json             # Final Report
│   └── bug_2001809_analysis_v1.json # Intermediate Refinement Version
├── raw_patches/
│   └── bug_2001809.diff             # Original Phabricator Patch
└── generated_fixes/
    └── bug_2001809_zeroshot.diff    # LLM-Generated Fix
```

## Troubleshooting
*   **429 Quota Exceeded**: If you see this error, use `run_batch.py` with a higher `--delay` (e.g., `--delay 120`).
*   **HTML in Diff**: Sometimes Phabricator returns HTML instead of a raw diff due to auth. The agent gracefully handles this by warning the user.