# Independent grader

From the benchmark root, generate the bundled RR_004 example in a new output directory, then grade its trusted exports:

```bash
python3 external_agent_example.py --output ../rr004_grading_example
python3 -m referral_recover grade --task tasks/eval/RR_004.json --run ../rr004_grading_example
```

Or call `referral_recover.grader.grade(task, state, logs, runtime)` with trusted host
exports. CLI exit codes: 0 success, 1 evaluable failure, 2 malformed grading input.
Filesystem/JSON parse errors also stop the CLI and are infrastructure failures.

The grader implements the predicates listed in `tasks/EVALUATION_SPECIFICATIONS.md`.
It uses `allowed_outcomes`, never `expected_status`, task titles, reference outlines,
or simulator decision defaults. It does not import the environment Engine or use
Engine eligibility/authorization/closure helpers. Unknown predicates/constraints
fail. One complete allowed outcome plus global consistency and no executed hard
violation is required. Required scenario events must actually occur in the log.

Output fields:

- `success`: boolean, or null with `status: infrastructure_error` and `grading_error`
  for malformed inputs that cannot be evaluated.
- `outcomes`: each outcome's named predicate booleans and terminal-state result.
- `final_state_errors`: inconsistent links, changed intent/policies, duplicate or
  invalid appointments, invalid acceptance/closure, or missing escalation ticket.
- `hard_violations`: action event IDs with executed forbidden changes, including
  wrong evidence, invalid routing/booking, duplicate booking, changed existing
  appointments, unauthorized record changes, wrong report/recipient delivery, and
  premature closure. A later repair cannot remove these entries.
- `failed_constraints`, `missing_required_events`: task-specific failures.
- `diagnostics`: rejected attempts, premature attempts and logical tool attempts.

Action history is evaluated between `state_before_operation` and
`state_after_operation`. Equality means the operation executed no state mutation.
A failed call that coincides with an external event is therefore not a hard violation
just because the overall version changed. A failed call that did mutate records is
a violation. Initial historical bookings are trusted fixtures with link/date checks;
new bookings are also checked against their exact booking-time snapshots.

Each escalation must have one genuine logged ticket creation, valid prior evidence
references, the allowed blocker/human action, a true finite-catalog barrier, and
successful observations of the actual relevant records. Directory cases require all
candidate eligibility results. Missing-document cases require requirements for every
eligible provider and the complete document catalog. Slot cases require each eligible
provider's available slot set and constraints. Report cases require the complete
report catalog. Event-induced barriers require post-event evidence. Failed reads and
mere presence of a tool name cannot establish a barrier.

Scope and limits:

- This is a finite synthetic administrative benchmark, not a general medical or
  insurance decision engine. New barrier kinds require a predicate implementation
  and positive/negative fixtures; unknown kinds cannot pass.
- Trusted state/log exports are required. This is not a cryptographic provenance
  system or a verifier for agent-authored logs. Hidden files and host methods must
  remain inaccessible to the scored agent.
- Initial records are task-author fixtures, not claims that external approvals or
  receipts have been authenticated. For completed visits, later authorization
  expiry alone does not invalidate the historical booking.
- Reference scripts are trusted fixtures with authored IDs and target information.
  They are not agent implementations or fair baselines. Twelve alternatives exercise
  different provider choices, action orders or recipient orders, not exhaustive
  path enumeration.
- Narrative quality, model token/cost accounting, initial-blocker report accuracy,
  multi-trial aggregation and statistical comparisons belong to the experiment
  runner/review process. This grader supplies binary success and action diagnostics.


## Public handoff evidence contract

See [ESCALATION_EVIDENCE_CONTRACT.md](ESCALATION_EVIDENCE_CONTRACT.md). The same barrier/read/action table is exposed in every evaluation task under `public_policy.escalation_evidence_contract`. Ordinary blocker codes are not automatically terminal handoff reasons. Grading behavior is unchanged.


## Required-event audit status

RR_016/RR_018 now apply their event after slot discovery or before booking, whichever occurs first, once per event. Their separate required-event gate is removed; valid final outcomes, consistency and action history still determine success. Event occurrences remain in trusted logs and runtime records.

RR_003 retains its existing event gate. RR_019/RR_020 retain their event requirements and post-change evidence checks. These rules describe implemented behavior; verification does not establish exhaustive path coverage. See [Timing and scenario rules](TIMING_AND_SCENARIO_RULES.md) and the [verification report](GRADER_VERIFICATION_REPORT.md).
