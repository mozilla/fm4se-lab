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

1. Clone the repository:
```bash
git clone <your-repo-url>
cd mozilla-bug-analyzer
```

2. Install dependencies:
```bash
pip install requests google-generativeai python-dotenv
```

3. Create a `.env` file:
```bash
echo "GOOGLE_API_KEY=your_gemini_api_key_here" > .env
```

4. Run the tool:
```bash
python bug_analyzer.py
```

## Usage

### Basic Usage

```bash
python bug_analyzer.py
```

When prompted, enter a Bugzilla bug ID (e.g., `2001809`).

### Example Output Structure

```
mozilla_bug_dataset/
├── json_data/
│   └── bug_2001809.json          # Structured metadata
├── raw_patches/
│   └── bug_2001809_D123456.diff  # Ground truth patch
├── human_reports/
│   └── bug_2001809_report.txt    # Comprehensive analysis
└── generated_fixes/
    └── bug_2001809_zeroshot.diff # LLM-generated fix
```

### Programmatic Usage

```python
from bug_analyzer import ComprehensiveBugAnalyzer

analyzer = ComprehensiveBugAnalyzer(gemini_api_key="your_key")

# Generate full report
report = analyzer.create_comprehensive_bug_report(bug_id=2001809)

# Generate zero-shot fix (for APR)
generated_fix = analyzer.generate_zero_shot_fix(report)
```

## Data Sources

### Bugzilla API
- Bug metadata (severity, priority, status)
- Description and reproduction steps
- Comments and discussions
- History and field changes

### Phabricator
- Code review differentials
- Reviewer feedback and status
- Raw patches (unified diff format)
- Commit associations

### Mercurial
- Commit hashes and messages
- Authorship and timestamps
- Repository information

### Searchfox
- Source code context
- File locations and structure
- Cross-references

## Output Formats

### JSON Metadata (`json_data/`)
Structured data including:
```json
{
  "bug_id": 2001809,
  "bug_data": {...},
  "bug_analysis": {
    "bug_type": "regression",
    "root_cause": "...",
    "severity_assessment": "high"
  },
  "differentials": [...],
  "fix_analysis": {...},
  "comprehensive_analysis": {...}
}
```

### Raw Patches (`raw_patches/`)
Standard unified diff format:
```diff
--- a/modules/libpref/StaticPrefList.yaml
+++ b/modules/libpref/StaticPrefList.yaml
@@ -1234,7 +1234,7 @@
-  value: true
+  value: false
```

### Generated Fixes (`generated_fixes/`)
LLM-generated patches for comparison with ground truth.

### Human Reports (`human_reports/`)
Comprehensive analysis including:
- Executive summary
- Root cause analysis
- Solution description
- Impact assessment
- Quality metrics
- Lessons learned

## Research Applications

### Automated Program Repair (APR)
Compare generated fixes against ground truth patches:
```python
ground_truth = read_file("raw_patches/bug_X_D123.diff")
generated = read_file("generated_fixes/bug_X_zeroshot.diff")
similarity = compute_patch_similarity(ground_truth, generated)
```

### Bug Triaging
Train models to predict:
- Severity levels
- Component assignments
- Fix complexity
- Time to resolution

### Code Review Quality
Analyze:
- Review thoroughness
- Reviewer expertise
- Feedback quality
- Iteration patterns

## Architecture

### Core Components

1. **BugzillaClient**: REST API interactions
2. **PhabricatorScraper**: Web scraping + API fallback
3. **MercurialClient**: Commit data retrieval
4. **SearchfoxClient**: Code context extraction
5. **LLMAnalyzer**: Gemini-powered analysis
6. **ReportGenerator**: Comprehensive report synthesis

### Data Flow

```
Bugzilla → Bug Data
    ↓
Phabricator → Code Reviews/Patches
    ↓
Mercurial → Commit Info
    ↓
Searchfox → Code Context
    ↓
LLM Analysis → Insights + Generated Fix
    ↓
Structured Dataset (JSON + Diffs + Reports)
```

## Configuration

### API Endpoints
```python
analyzer = ComprehensiveBugAnalyzer(
    bugzilla_url="https://bugzilla.mozilla.org",
    phabricator_url="https://phabricator.services.mozilla.com",
    hg_url="https://hg.mozilla.org",
    searchfox_url="https://searchfox.org",
    gemini_api_key="your_key"
)
```

### LLM Model
Current default: `gemini-2.5-flash`
- Fast analysis
- High quality summaries
- Good code understanding

To use a different model:
```python
self.model = genai.GenerativeModel('gemini-pro')
```

**Note**: This tool is for research and analysis purposes. Respect Mozilla's terms of service and rate limits when collecting data.