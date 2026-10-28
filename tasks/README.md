# Task specifications

The benchmark has 20 originally authored evaluation tasks (`eval/RR_001.json`–`RR_020.json`) and four separate development tasks (`dev/DEV_001.json`–`DEV_004.json`). The current provisional distribution is 7 easy, 7 medium and 6 hard, with justified escalation cases RR_007, RR_008, RR_014, RR_019 and RR_020.

Schema and contract version fields identify technical formats.

Start with `EVALUATION_SPECIFICATIONS.md`, `evaluation_task.schema.json`, and `../README.md`.

From the repository root:

```bash
python3 tasks/validate_evaluation_specs.py
python3 tasks/validate_recovery_paths.py  # read-only by default
python3 -m unittest discover -s tests -q
```

Use `python3 tasks/validate_recovery_paths.py --export` **only when deliberately regenerating** the trusted traces and fixture summary. Do not use evaluation tasks to tune agent prompts or controller decisions.
