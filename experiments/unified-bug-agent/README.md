# Unified Bug Agent

An AI-powered agent designed to automatically analyze, reproduce, and fix software bugs by leveraging multiple data sources (Bugzilla, CrashStats, Phabricator, Searchfox, Mercurial).

## Features
- **Multi-Source Context**: Fetches data from Bugzilla, CrashStats, and Phabricator.
- **Code Search**: Uses Searchfox (with GitHub fallback) to find relevant code.
- **Similar Bug Analysis**: Identifies patterns from historically resolved bugs.
- **Automated Refinement**: "Critique-and-Refine" loop to ensure high-quality analysis.
- **Zero-Shot Fixing**: Generates unified diff patches based on the final analysis.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Environment Variables**:
    Create a `.env` file or set the following environment variables:
    ```bash
    GEMINI_API_KEY=your_key_here  # Or OPENAI_API_KEY, ANTHROPIC_API_KEY
    LLM_PROVIDER=gemini           # Options: gemini, openai, claude, deepseek
    PHABRICATOR_TOKEN=your_token  # Optional, for Phabricator access
    ```

## Usage

### Single Bug Mode
Run the agent on a single bug ID:

```bash
python main.py --bug_id 2001809
```
The report will be saved to `output.json`.

---

### Batch Execution Mode (New)

Run the agent on a large set of bugs with automated artifact organization.

#### 1. Fetch Diverse Bugs
Automatically retrieve a diverse list of resolved bugs from various components (e.g., Graphics, Networking, DOM):

```bash
python fetch_bugs.py --count 20 --output bugs.txt
```

#### 2. Run Batch Process
Execute the agent on the list of bugs. This process is sequential to respect API rate limits.

```bash
python batch_run.py --input bugs.txt --output-dir results --start 1 --end 10
```

#### 3. Output Structure
The results are organized hierarchically:

```text
results/
├── 12345/
│   ├── original_bug_report.json  # Raw data from Bugzilla
│   ├── comprehensive_report.json # Full analysis, context, and trace
│   ├── generated_fix.diff        # The generated patch
│   └── execution.log             # Dedicated logs for this run
├── 67890/
│   └── ...
└── batch_summary.json            # Summary of successes/failures
```
