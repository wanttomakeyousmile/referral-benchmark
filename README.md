# Referral recovery benchmark

Twenty synthetic outpatient referral recovery tasks, four development tasks, a Python/SQLite simulator, a public tool interface, and an independent state-and-history grader. Clinical diagnosis and treatment are outside scope.

Start with [External agent quickstart](EXTERNAL_AGENT_QUICKSTART.md) and the [documentation index](docs/README.md).

## Reproduce locally

Python 3.10+; the local test suite uses the standard library.

```bash
python3 -m unittest discover -s tests -q
python3 tasks/validate_evaluation_specs.py
python3 tasks/validate_recovery_paths.py
python3 external_agent_example.py --output ../rr004_example
python3 worked_example_rr016.py --output ../rr016_reproduction
python3 scripts/verify_grader.py . ../grader_reproduction
```

Use new output directories. Structural validation prints its summary; use --output to save a detailed report; recovery validation is read-only by default.

## Examples and validation

Use the [representative inputs](docs/representative_inputs/README.md) to inspect session contexts and the [RR_016 worked example](docs/worked_example_rr016/README.md) to follow tool calls and grading. The [grader verification report](docs/GRADER_VERIFICATION_REPORT.md) describes the bundled verification checks.

## Access boundaries

This public research source contains answers, hidden fixtures and trusted grading evidence. Public availability does not make those files permissible agent input. Scored agents receive only session context, schemas and tool observations; evaluators must enforce that boundary. The Python session interface is not a sandbox for untrusted executable agents.
