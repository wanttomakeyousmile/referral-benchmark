# External agent quickstart

Run commands from the repository root. Python 3.10+ is required. The simulator, example and unit tests use the standard library. No API keys, model calls or pip installs are required. Optional `jsonschema` checks are separate from the core tests.

## 1. Create an isolated environment

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python --version
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe --version
```

On Windows, replace `python` in the following commands with `.\.venv\Scripts\python.exe`. Commands are tested on Linux only. Running from the repository root makes the local package importable. Keep `tasks/` and `docs/` beside the source. Installing the Python module alone does not supply the complete benchmark data.

## 2. Run the benchmark tests

```bash
python -m unittest discover -s tests -q
```

Expect 89 benchmark tests to pass. The structural task validator prints a summary; use --output PATH to save its detailed report.

## 3. Run the independent integration example

```bash
python external_agent_example.py --mode accept-demo --output example_runs/accepted
python external_agent_example.py --mode read-only --output example_runs/read_only
```

Both output directories must be new. The first demonstration reads and submits the already complete RR_004 packet and expects `success: true`. The read-only demonstration expects `success: false`. Both commands exit successfully when their expected result is observed. These are fixed integration checks, not general agents or model baselines. They import no team controller.

Each run stores `public_context.json`, `public_transcript.jsonl`, the agent report, evaluator exports and `grade.json`. Only the first two are suitable for a blind reviewer. Keep SQLite state, full action logs, runtime exports and grade results evaluator-only until the initial review judgment is recorded.

## 4. Run the grader independently

```bash
python -m referral_recover grade --task tasks/eval/RR_004.json --run example_runs/accepted
python -m referral_recover grade --task tasks/eval/RR_004.json --run example_runs/read_only
```

The grading CLI exits 0 for success, 1 for task failure and 2 for an infrastructure result when valid exports are available. The second command should return 1. Missing or malformed files can raise a command error and must not be treated as task failure.

## 5. Reset or start another attempt

```bash
python -m referral_recover reset --db example_runs/read_only/environment.sqlite
```

Reset clears the database attempt and invalidates its old session. It does not erase old JSON exports. Preserve evidence before resetting, then export again before grading. Prefer a new output directory for each real attempt. The example intentionally refuses an existing directory.

## 6. Connect your own agent

In `external_agent_example.py`, the host creates the environment and passes three public capabilities to `run_agent`: context, tool definitions and a call function. Replace the demonstration decisions with your agent loop. Provide the model with the goal, public policies, schemas and observed responses. Dispatch each tool name and argument object through the call function. Preserve returned observation IDs, use distinct call IDs for new logical calls, and declare budgets and stopping rules.

The host loads task JSON and owns grading. Do not pass task JSON, reference paths, grader code, database access or full exports to the agent. This local Python separation prevents accidental leakage but is not a security sandbox. An untrusted executable agent needs a separately isolated process/service with only the public interface exposed.

## Specifications

- Tool schemas: `docs/tool_definitions.json` (20 tools).
- Public context and policies: `session.context()` and task public-policy fields.
- Shared escalation policy: `tasks/escalation_evidence_policy.json` and `docs/ESCALATION_EVIDENCE_CONTRACT.md`.
- Complete evaluator task specifications: `tasks/eval/` (20 tasks), `tasks/dev/` (4 cases), `tasks/EVALUATION_SPECIFICATIONS.md`, and `tasks/evaluation_task.schema.json`.
- Grading: `docs/GRADING_SPEC.md`, `docs/INTERFACE_AND_GRADING.md`, `referral_recover/grader.py`.
