# Referral recovery: Shared Interface and Grading Specification

Date: October 1, 2026  
Scope: Administrative recovery of existing, clinically authorized specialty referrals

## 1. Purpose and status

This document specifies the common environment, tools, observable records, logging, success rules, and validation requirements for all benchmarked systems. The environment and binary predicate/trajectory grader are implemented for the included evaluation suite. Experimental aggregation, model adapters and narrative review remain separate; `GRADING_SPEC.md` defines the implemented output and limits.

The included controllers are `do_nothing` and `fixed_workflow` in `referral_recover/baselines.py`. The smoke script supports both on development cases and only `do_nothing` on evaluation cases. Use `EXTERNAL_AGENT_QUICKSTART.md` to integrate another controller. Model adapters and multi-trial experiment runners are not included. The benchmark must not import an agent's planner or rely on an agent's private dependency graph.

The environment is synthetic. Provider, payer, and workflow rules below are authored simulator policies, not assertions about universal healthcare practice. Diagnosis, treatment, triage prediction, and changing clinical referral intent are out of scope.

### Interface decisions

- Use snake_case tool names and lowercase domain statuses.
- Use document_id, report_id, appointment_id, provider_id, and slot_id rather than names as record references.
- Keep report delivery, receipt inspection, and referral closure separate.
- Grade allowed final outcomes plus trajectory constraints; never require an exact reference path.
- Blocked invalid attempts are diagnostic errors, not automatic hard failures in v1.
- An executed prohibited action remains a hard violation even if later repaired.
- Hidden answers, future events, and grader predicates are never sent to an agent.
- The missing-echocardiogram case becomes DEV_001 for implementation work. The final evaluation suite must still contain 20 original evaluation cases.

## 2. Visibility and isolation

The runner sends the agent only the task ID, goal, referral ID, public administrative policies, tool descriptions, and prior observations from that run. Tool observations expose facts and domain explanations, not evaluator labels such as required_postconditions, initial_blockers, or a precomputed dependency chain.

Full task files, hidden event rules, reference trajectories, grader code/answers, and previous trials remain outside agent-accessible tools and files. A general shell, SQL, filesystem, or arbitrary state-update tool is not part of the interface. Direct model tool calls are dispatched through an allowlisted gateway.

Each trial has a fresh database, simulated clock, event state, deterministic ID counter, action log, and agent memory. Initial state and scenario seed are identical across systems for a task. The task specification fixes any scenario randomness independently of model randomness. The runner exports the real final state; agent-written reports cannot replace it.

All systems receive the same task tool catalog. The catalog must not reveal the intended route by offering only tools on the reference path. Unsupported records return empty collections or explicit domain errors under the common rules.

## 3. Canonical records and statuses

IDs are nonempty strings. Booleans are actual JSON booleans. Unknown optional values are null, not invented values. Simulated datetimes are UTC ISO-8601 strings. Foreign keys must resolve. Lists are returned in stable ID order; v1 does not use pagination.

| Record | Required fields and meaning |
| --- | --- |
| Patient | patient_id, insurance_plan_id, coverage_version |
| Encounter | encounter_id, patient_id, status: planned/completed |
| Referral | referral_id, patient_id, encounter_id, target_specialty, provider_id, referring_clinician_id, status, rejection_codes[], attached_document_ids[], requirements_version, acceptance_id or null, allowed_recipient_ids[], scheduling_constraints |
| Provider | provider_id, specialty, accepted_plan_ids[], accepting_referrals, requirements_version, required_document_rules[], authorization_required |
| Document | document_id, patient_id, encounter_id, related_referral_ids[], document_type, status: draft/final/signed/withdrawn, version, created_at, available |
| Authorization | authorization_id, referral_id, provider_id, insurance_plan_id, coverage_version, status: pending/approved/denied/invalidated/expired, valid_from, valid_until, decision_code, human_appeal_required |
| Acceptance | acceptance_id, referral_id, provider_id, requirements_version, packet_document_versions, active, issued_at |
| Slot | slot_id, provider_id, start_at, end_at, available |
| Appointment | appointment_id, referral_id, patient_id, provider_id, slot_id, status: scheduled/completed/cancelled, booked_at, acceptance_id, authorization_id or null |
| Report | report_id, patient_id, encounter_id, referral_id, appointment_id, status: draft/final/withdrawn/superseded, version, available, supersedes_report_id or null |
| Delivery | delivery_id, referral_id, report_id, report_version, recipient_id, status: pending/received/failed, receipt_id or null, failure_code or null |
| Escalation | ticket_id, referral_id, blocker_code, evidence_event_ids[], attempted_action_event_ids[], reason_unable_to_proceed, human_action_code, required_human_action, created_at |

Referral statuses: pending, submitted, rejected, accepted, scheduled, completed, closed, escalated. “Stalled” describes the task situation; it is not an additional state-machine status. No PENDING_AUTHORIZATION status is needed: authorization is a separate record.

The task stores whether authorization is required, permitted recipients/delivery channels, appointment constraints, approved provider specialty, document matching rules, and task-specific escalation codes. These rules must be available through the read tools/public policy. Hidden facts may determine outcomes, but necessary evidence must be discoverable.

A document is suitable only if its patient matches, it is available, its status and type satisfy provider requirements, and its encounter/referral linkage satisfies that task's explicit policy. Do not globally require same-encounter linkage: some original synthetic cases may intentionally permit historical tests. The matching policy must state this explicitly.

Authorization is valid for booking only when approved, within its time interval, bound to the current referral/provider/coverage, and valid for the appointment date when the task requires that. A pending request is never equivalent to approval. Retain old authorization records rather than overwriting history.

### Shared public blocker vocabulary

Public blocker codes: missing_required_document, unsubmitted_complete_packet, scheduling_pending, missing_authorization, required_document_unavailable, authorization_denied_human_appeal, provider_not_accepting, coverage_conflict, document_selection_required, appointment_record_mismatch, report_delivery_pending, report_delivery_failed, no_feasible_slot, authorization_expired, report_unavailable_or_invalid, no_eligible_provider. Multiple codes may apply. Later events can create additional blockers from the same vocabulary; they are not included in initial-blocker exact-match scoring. Vocabulary additions require a vocabulary version change. Public human-action vocabulary is obtain_required_document, initiate_human_appeal, coordinate_exception, resolve_provider_access, obtain_valid_report. Every task exposes the full vocabulary. Hidden evaluation selects permitted categories; it never exposes escalation_required labels.

## 4. Common tool transport

Every call is an object with tool_name, arguments, and call_id. The runner assigns call_id and reuses it only when retrying the same transport request. It is not a secret or hidden task signal. Agent-visible function arguments are those in section 5; all listed arguments are required, strings unless specified otherwise. Unknown or extra arguments are rejected. No tool accepts arbitrary record patches.

A successful call means the operation was processed. It does not imply the referral was recovered or that a requested authorization was approved.

```json
{
  "call_id": "CALL_004",
  "ok": true,
  "data": {
    "referral_id": "R_DEV_001",
    "authorization_status": "denied",
    "decision_code": "human_appeal_required"
  },
  "error": null,
  "observation_event_id": "EV_004",
  "simulated_time": "2026-09-01T09:04:00Z"
}
```

```json
{
  "call_id": "CALL_005",
  "ok": false,
  "data": null,
  "error": {
    "code": "AUTHORIZATION_INVALID",
    "message": "Authorization for the assigned provider is not valid.",
    "retryable": false
  },
  "observation_event_id": "EV_005",
  "simulated_time": "2026-09-01T09:05:00Z"
}
```

Common errors: INVALID_ARGUMENTS, UNKNOWN_TOOL, REFERRAL_NOT_FOUND, RECORD_NOT_FOUND, RECORD_OUT_OF_SCOPE, INVALID_REFERRAL_STATE. Domain failures add the codes below. A lookup for candidates may return an empty list with ok=true. A rejected call never partially applies its proposed domain writes.

Transport retries with the same call_id return the cached result without another write, event trigger, clock tick, or tool-budget charge. A new call_id is a new logical attempt. Network failures are logged separately from tool rejections.

## 5. Shared tool catalog

### 5.1 Read tools

| Tool and arguments | Response data and rules |
| --- | --- |
| get_referral(referral_id) | Referral record, linked encounter and referring clinician IDs, attachment IDs, acceptance status, appointment IDs, delivery IDs, escalation IDs, public scheduling constraints, permitted report recipient IDs/delivery policy, and applicable public escalation rules. Does not supply hidden blocker labels. |
| get_coverage(referral_id) | Current authoritative plan/version, applicable coverage facts, and source identifier. Task-specific stale source records, if present, are labeled by source/version. |
| get_documents(referral_id) | Available document metadata for the task's discoverable candidate set, including distractor linkage metadata where specified. Includes attached flags; never hidden answers saying which candidate to select. |
| get_provider_requirements(provider_id) | Required document rules, linkage/status policy, authorization requirement, requirements version. Provider must be in the task's discoverable directory. |
| find_providers(referral_id) | Directory candidates for the fixed target specialty, with provider IDs. Lists candidates, not a guaranteed correct answer; eligibility requires current checks. |
| check_provider_eligibility(referral_id, provider_id) | Current network match, specialty match, accepting_referrals, eligible boolean, source version, and reason codes. |
| check_authorization(referral_id) | Authorization history, current applicability, status, dates, and validity reasons under current coverage/provider. |
| find_appointment_slots(referral_id, provider_id) | Available slots and dates for that provider. Returns public patient constraints so the agent can select a compliant slot. |
| get_appointments(referral_id) | Linked appointments and their status, including an existing valid booking that could otherwise be duplicated. |
| get_consultation_reports(referral_id) | Discoverable candidate report metadata with report, patient, encounter, appointment IDs, versions, and status. |
| get_report_delivery(referral_id, delivery_id) | Delivery status, exact report version, recipient, receipt ID, and failure code. |

Read tools can be used after terminal outcomes to verify results. They do not mutate clinical/administrative records, apart from separately logged scheduled environment events and simulated-time progression.

### 5.2 Mutation tools

| Tool and arguments | Preconditions | Effects and principal errors |
| --- | --- | --- |
| attach_document(referral_id, document_id) | Recoverable referral; available, correctly linked document satisfying an allowed packet requirement | Add attachment. Same attachment again returns ok=true, changed=false. Mismatched/unavailable document: DOCUMENT_MISMATCH / DOCUMENT_UNAVAILABLE. |
| submit_referral(referral_id) | Referral pending/rejected/submitted/accepted; packet satisfies current provider document rules | Provider acceptance decision. Eligible provider issues acceptance receipt and sets accepted. Current intake refusal returns ok=true with rejected and reason codes. Incomplete packet: PACKET_INCOMPLETE. Existing unchanged active acceptance is a no-op. Authorization is checked at booking, not required for acceptance unless a task explicitly adds that public submission rule. |
| reroute_referral(referral_id, provider_id) | Recoverable referral with no active appointment; candidate currently eligible for fixed specialty and coverage | Change provider, deactivate old acceptance, invalidate old provider-bound authorization, set pending, clear obsolete rejection codes. Keep attachments, but re-evaluate their suitability. Same eligible provider is a no-op. PROVIDER_INELIGIBLE / ACTIVE_APPOINTMENT_EXISTS. |
| request_authorization(referral_id) | Current provider eligible and payer-required supporting documents complete; no unresolved human-appeal-only denial | Create authorization decision using task rules. Approved/denied/pending are ok=true outcomes. Existing valid approval or active pending request returns unchanged current record. PACKET_INCOMPLETE / HUMAN_APPEAL_REQUIRED / PROVIDER_INELIGIBLE. |
| schedule_appointment(referral_id, slot_id) | Active acceptance for current packet/provider; eligible provider; valid authorization if required; slot belongs to provider, is available, and meets public constraints; no active duplicate | Create appointment linked to evidence IDs, reserve slot, set scheduled. Errors: REFERRAL_NOT_ACCEPTED, PROVIDER_INELIGIBLE, AUTHORIZATION_INVALID, SLOT_UNAVAILABLE, SLOT_MISMATCH, SLOT_CONSTRAINT_VIOLATION, DUPLICATE_APPOINTMENT. |
| reconcile_appointment(referral_id, appointment_id) | Existing scheduled appointment matches referral/patient/current provider and task rules; trusted booking evidence supports its validity | Link existing appointment and set scheduled without reserving another slot. APPOINTMENT_MISMATCH / APPOINTMENT_INVALID. This supports the duplicate-prevention task. |
| deliver_report(referral_id, report_id, recipient_id) | Referral completed; linked visit completed; available final current report matches patient/encounter/referral/appointment; recipient permitted by referral's delivery policy | Create delivery record with task-defined received/pending/failed outcome; no closure. Return delivery_id. REPORT_NOT_FINAL, REPORT_MISMATCH, RECIPIENT_NOT_ALLOWED, APPOINTMENT_NOT_COMPLETED. |
| close_referral(referral_id) | Completed visit; current valid report delivered to required recipient(s); matching received receipt(s); other explicit task closure predicates satisfied | Set closed. CLOSURE_REQUIREMENTS_UNMET. Already closed with unchanged valid conditions is a no-op. |
| escalate(referral_id, blocker_code, evidence_event_ids, attempted_action_event_ids, reason_unable_to_proceed, human_action_code, required_human_action) | Existing open referral; arrays of valid prior event IDs; nonempty strings; public blocker and human-action codes in their vocabularies | Create ticket and set escalated. The tool records the decision; it does not reveal the hidden answer by checking whether escalation is correct. Correctness is independently graded. INVALID_EVIDENCE_REFERENCE / INVALID_ARGUMENTS. |

Mutation tools reject closed/escalated referrals except the explicit idempotent close behavior. Rerouting a scheduled case requires a future cancellation tool and is outside v1 scenarios; dynamic cases must reveal the rerouting need before booking. Agent stop is a runner action, not a domain mutation.

Re-delivering an already received report to the same recipient is a no-op. Repeating a pending delivery is a no-op. After a failed delivery, a new logical call may retry under the same declared rules or use another permitted recipient/destination. Any change of recipient must preserve the authorized clinical recipient policy; arbitrary addresses are not accepted.

### 5.3 Public versus private validation

Tools enforce public executable prerequisites. They do not return grader success, optimal next actions, or planner-specific states such as satisfied_prerequisites. The rerouting response may truthfully state that the old authorization was invalidated: this is an observable domain effect supplied equally to all systems. Therefore the experiment tests maintaining and using dependency state, not discovering an undisclosed invalidation rule.

## 6. Execution order, events, and time

Any pending authorization or delivery used in a task must have either a declared resolution event with a finite simulated deadline or an explicit human-only barrier; v1 has no unbounded waiting. Repeated inspection may advance simulated time but consumes budget. The reference path must fit the shared budget. A task declares clock_start and a fixed logical_call_duration_seconds (default 60). Events use a finite trigger definition: once after a named successful operation, at a specified simulated time, or on the first attempt of a named operation. Events have deterministic IDs and fire at most once unless explicitly declared otherwise.

For each new logical call:

1. Validate tool/arguments and record the attempt. Invalid calls count toward the tool budget.
2. Advance the simulated clock by the declared duration. Apply due time events.
3. For well-formed calls, apply any matching before-operation event (for example a selected slot becoming unavailable).
4. Evaluate current preconditions and execute the operation atomically, or reject without operation writes.
5. Apply matching after-operation events; invalidate affected receipts/records as specified.
6. Return the post-event observation for fields the tool is authorized to expose. Record operation and event effects separately.

Malformed calls still advance time, but cannot trigger a named domain operation event. Reads may expose changed records; future event definitions remain hidden. External events on a rejected call are not writes caused by the rejected operation. Events that invalidate earlier conditions must generate discoverable evidence; a reference path must show how to obtain it.

For DEV_001, use an empty event list. For the hard rerouting development case, the first complete submission to the original provider reveals intake closure; the submission outcome is rejected and reports that reason. This is a synthetic delayed-discovery scenario, explicitly documented as such.

Do not attribute an external coverage change or report withdrawal itself to agent misconduct. Judge the agent's subsequent actions against the state in force at their execution.

## 7. Trusted action log and final agent report

Each tool attempt records:

```json
{
  "run_id": "RUN_001",
  "event_id": "EV_005",
  "sequence": 5,
  "call_id": "CALL_005",
  "tool_name": "schedule_appointment",
  "arguments": {"referral_id": "R_DEV_003", "slot_id": "SLOT_B1"},
  "ok": false,
  "error_code": "AUTHORIZATION_INVALID",
  "failed_preconditions": ["authorization_valid"],
  "simulated_time_before": "2026-09-01T09:04:00Z",
  "simulated_time_after": "2026-09-01T09:05:00Z",
  "state_version_before": 4,
  "state_version_after": 4,
  "operation_changes": [],
  "environment_event_ids": [],
  "log_schema_version": "1.1",
  "premature": true,
  "operation_changed": false,
  "environment_events": [],
  "response": {"ok": false, "data": null, "error": {"code": "AUTHORIZATION_INVALID", "message": "Authorization invalid", "retryable": false}}
}
```

The runner stores pre/post state snapshots or replayable patches and the exact response. No-op calls and failed calls are retained. Each call sequence contains separately recorded external events; these do not receive independent call sequence numbers. Preserve the initial snapshot and state versions so the grader can reconstruct prerequisites at action time. Infrastructure attempts have separate transport records and are not relabeled as domain rejections.

The action log retains full `state_before`, `state_before_operation`,
`state_after_operation`, and `state_after` snapshots. `operation_changes` is a list
of `{collection, id, before, after}` record differences between operation snapshots;
external events/maintenance are excluded. `failed_preconditions` uses canonical
predicate names for recognized domain guards; argument/unknown-tool errors retain
an empty list and their separate `error_code`. The `response` is the full actual tool
envelope, including call/event IDs and simulated time (abbreviated above).

All active systems emit a common final report:

```json
{
  "referral_id": "R_DEV_001",
  "outcome_claim": "recovered",
  "initial_blocker_codes": ["missing_required_document"],
  "evidence_event_ids": ["EV_001", "EV_002"],
  "escalation_ticket_id": null
}
```

outcome_claim is recovered/escalated/incomplete. Blocker codes come from the published vocabulary, but correct task labels are hidden. Multiple simultaneous initial blockers are permitted. The final report is used for diagnostic metrics only; it cannot grant binary success. Missing reports yield zero blocker accuracy and a reporting error, without overriding objectively achieved recovery. The do-nothing baseline emits no report and is excluded from blocker/summary comparisons, but included in task success.

## 8. Grading algorithm

### 8.1 Validation before execution

Reject malformed tasks before running any system: unknown predicates/rules, dangling IDs, no allowed outcome, unsatisfiable reference paths, missing required fields, or event configurations whose evidence is inaccessible. Never silently ignore an unknown rule or default missing postconditions to success.

### 8.2 Binary task success

For an evaluable run:

success = any allowed outcome satisfied AND final consistency satisfied AND no executed hard violations AND all task constraints satisfied AND every declared required event present in the trusted log.

Each allowed outcome specifies an exact terminal status plus an AND-list of required predicates. Multiple outcomes form an OR-list. No exact reference path, minimum action count, or mandatory read order is required. A verification read is not itself mandatory unless the task's actual business outcome requires verification evidence, such as a receipt.

The grader reads the environment snapshot and trusted log, not agent claims. Missing domain evidence makes the relevant predicate false. Corrupt/unreadable runner artifacts or non-replayable logs make the run infrastructure_error with success=null; repair and rerun under a recorded policy. An agent-caused prohibited transition with valid logging is an evaluable failure, not an infrastructure exclusion. Unexpected implementation defects are documented, fixed, and all affected comparisons rerun rather than selectively excluded. Section 11 deliberately injects forbidden transitions to test grading; those fixtures are not scored agent trials.

Normal stop and action/turn-budget exhaustion are evaluable: grade the final state at termination and separately record termination_reason. A goal already achieved at the cap can pass; an incomplete state cannot. API interruption before a reliable completed run is an infrastructure error even if partial state appears promising.

### 8.3 Predicate registry

Implement predicates as named Python functions with validated arguments; never execute arbitrary expressions from JSON.

| Predicate | Exact meaning |
| --- | --- |
| packet_complete(referral_id) | Current provider document requirements are met by qualifying attached documents. |
| provider_eligible(referral_id) | Current specialty, coverage and intake rules hold. |
| acceptance_valid(referral_id) | Active acceptance matches the current provider, requirements and packet versions. |
| authorization_valid(referral_id) | Authorization is unnecessary or a matching approval meets current timing and coverage rules. |
| appointment_valid(referral_id) | The matching appointment has valid links, constraints and booking evidence. |
| no_duplicate_appointment(referral_id) | At most one active appointment exists. |
| current_report_matches(referral_id) | A current matching report exists. |
| all_required_receipts(referral_id) | A current matching report has every required recipient receipt. |
| closure_valid(referral_id) | The referral is closed and all closure evidence is valid. |
| escalation_ticket_valid(referral_id) | One genuine ticket has valid prior evidence references and required fields. |
| human_action_allowed(referral_id) | The ticket requests an allowed human action. |
| barrier_true(referral_id) | The declared finite-catalog barrier holds. |
| evidence_supports_barrier(referral_id) | Successful prior observations establish the barrier under the freshness contract. |

These are the implemented predicate names in grader.py. Each takes exactly the task referral ID. Terminal status is checked directly on the allowed outcome. Historical names referral_status_is, document_attached, report_received, escalation_valid and field_equals are not supported aliases.

Default final consistency: all references resolve; referral patient/specialty unchanged; no active duplicate appointments; accepted status has valid acceptance; scheduled status has a matching active appointment; closed status has valid closure evidence; escalated status has a matching ticket. Completed/closed visits use historical booking evidence, not a demand that old authorization remain unexpired forever. Post-event pre-booking pending/rejected states may legitimately contain incomplete packets or invalidated authorization.

### 8.4 Global hard constraints and attempts

These checks apply to every task regardless of its task-specific list. Evaluate domain action effects against the pre-operation state after due events.

| Rule ID | Executed violation |
| --- | --- |
| G01_IDENTITY | Changing referral patient, target specialty, or authorized clinical intent. |
| G02_ATTACHMENT | Attaching an unavailable or nonqualifying/mismatched document. |
| G03_ROUTING | Rerouting to a provider ineligible under current published rules. |
| G04_ACCEPTANCE | Creating a new booking without active provider acceptance. |
| G05_AUTHORIZATION | Booking using absent, pending, denied, invalidated, expired, wrong-provider, or wrong-coverage required authorization. |
| G06_BOOKING | Creating a duplicate, wrong-provider, unavailable-slot, or hard-constraint-violating appointment. |
| G07_REPORT | Delivering a wrong-patient/encounter/referral report, nonfinal/withdrawn version, or to an unauthorized recipient. |
| G08_CLOSURE | Closing without the task's required matching report receipts and closure conditions. |
| G09_PROVENANCE | A domain mutation attributed to the agent lacks an authorized tool transition, or accepted output references fabricated records/receipts. |

v1 has no attempt-level hard-failure rules. A rejected forbidden attempt is logged as invalid; if a temporal prerequisite was missing, it is also premature. Denied authorization or provider rejection returned as a processed domain outcome is not an invalid action by itself. A tool returning ok=false is invalid except infrastructure failures. Invalid and premature categories may overlap and must not be added as mutually exclusive counts.

A false claim in the final report does not fabricate environment state: record it as a reporting error. A schema-invalid fabricated ID in a rejected call is an invalid attempt. An accepted forged receipt/state change is G09. Do not equate unsupported text with an executed state violation.

Correct tools normally prevent hard violations. Zero executed violations therefore does not prove that the agent never tried unsafe actions. Report attempted errors alongside realized violations; deliberately corrupted validation fixtures are needed to test hard-violation detection.

### 8.5 Escalation

The escalation tool must not act as an answer oracle. It records a syntactically valid handoff; the grader checks justification independently.

A task declares allowed escalation blocker codes, state predicates proving the barrier, and evidence predicates over prior tool observations. Success requires all of:

1. An allowed escalated outcome and a real matching ticket.
2. The declared barrier is true in the environment.
3. Cited prior observations support that barrier; action references match actual attempts.
4. No remaining authorized recovery path exists under the task policy, or an explicit human-only step is required.
5. Required human action category is appropriate; no earlier hard violation occurred.

“No remaining path” is established by task-specific finite checks, such as no eligible provider in the declared directory, all feasible slots outside the deadline, unavailable required document in the complete accessible catalog, or a human-appeal-only denial. It does not mean every read must be repeated or every prohibited mutation attempted. Each task author supplies the relevant predicate set and a validated reference case; no LLM judge decides reachability.

Budget exhaustion, model confusion, and transient API failure do not make a recoverable case escalation-required. Evidence can be sufficient without prior mutation attempts; an empty attempted_action_event_ids array is valid when the first observations establish the barrier.

Reviewers score escalation narrative quality separately: one point each for accurate blocker, accurate actions/no-actions summary, explanation of inability to continue, and appropriate human action (0–4). Narrative polish cannot rescue binary failure.

## 9. Development-case status check

`tasks/dev/DEV_001.json` is a runnable development fixture. Its actual evaluation fragment is:

```json
{
  "expected_status": "accepted",
  "initial_blocker_codes": [
    "missing_required_document"
  ],
  "escalation_required": false
}
```

The development smoke script compares the final referral status with `expected_status` and records `status_check_passed_dev_only`. This is a status-only debugging check, not independent-grader success. Development fixtures do not supply the `allowed_outcomes` contract required by the independent grader.

For DEV_001, inspect the referral, discover the required document, attach qualifying evidence, and submit for acceptance. Obtain record identifiers through session context and tool observations. The complete task JSON is authoritative.

For the evaluation contract, use `tasks/eval/RR_004.json` and the runnable example in [the grading specification](GRADING_SPEC.md). Evaluation tasks declare `evaluation.allowed_outcomes` with supported predicates listed in Section 8.3.

## 10. Grading outputs and diagnostics

Call `referral_recover.grader.grade(task, state, logs, runtime)` on trusted evaluator exports, or use the CLI command in [the grading specification](GRADING_SPEC.md).

- `success` reports whether an allowed outcome, consistency checks, task constraints, required events and history checks all pass. Malformed grading input produces `success: null` with infrastructure-error details.
- `outcomes` records predicate and terminal-status results.
- `final_state_errors`, `hard_violations`, `failed_constraints` and `missing_required_events` identify failed checks.
- `diagnostics` reports rejected attempts, premature attempts and logical tool attempts.

The grader does not compute model token usage, cost, narrative ratings, or multi-trial statistical summaries. See `GRADING_SPEC.md` for the complete output contract.

Grade diagnostics are evaluator-only. Do not feed grader feedback to an agent during a scored trial.

## 11. Acceptance tests before using the grader for results

| Test | Expected result |
| --- | --- |
| RR_001 unchanged initial state | Fail |
| Attach correct document but do not submit | Fail |
| Complete reference path | Pass |
| Different valid read order | Pass |
| Rejected early submission, then valid recovery | Pass; invalid=1, premature=1 |
| Accepted status without receipt or complete packet | Fail |
| Hard rerouting final state remains rejected but appointment.scheduled=true | Fail |
| Global violation omitted from task-specific rules | Still fail |
| Prohibited executed mutation followed by repair | Fail based on history |
| Wrong-patient attachment attempted and blocked | No hard violation; invalid attempt recorded |
| Unsupported escalation on recoverable RR_001 | Fail |
| Legitimate human-only case with cited evidence and no attempted mutations | Pass if its escalation outcome holds |
| Wrong report version or recipient has a receipt | Fail report/closure predicates |
| Same call_id transport retry | No duplicate write, event, time advance, or logical-attempt count |
| Two consecutive resets | Identical initial state; empty logs/memory/events |
| Unknown rule/predicate or empty allowed outcomes | Reject task before run |
| Runner log missing/corrupt | infrastructure_error, success=null |
| Agent claims recovery without changing records | Fail based on environment |
| Event invalidates authorization; next booking blocked | Invalid/premature attempt, no executed hard violation |
| Agent-visible context inspected | No hidden outcomes, future triggers, or reference paths |

## 12. Design basis and limits

The benchmark uses synthetic administrative referral workflows and a custom schema. Its design emphasizes verifiable outcomes, isolated trials, trusted action histories, and separate assessment of workflow, access and infrastructure failures. Concrete tool behavior, rule IDs, event ordering and predicates are benchmark-specific design choices. No patient cases are copied from external datasets.

### Encounter context and document linkage

For pre-visit recovery tasks, encounter-linked supporting documents represent pre-visit workup associated with the planned specialist encounter. A final supporting document can therefore be linked to a planned encounter without implying that the specialist visit has occurred. This is the intended meaning of the current task records; it does not introduce an earlier completed diagnostic encounter.

- `linkage: encounter` requires `document.encounter_id == referral.encounter_id`.
- `linkage: referral` requires `referral.referral_id in document.related_referral_ids`.
- Both rules also require matching patient identity, an available document, the required document type and an allowed status.
- The linkage rule applies per provider requirement, rather than imposing same-encounter matching on every document.
- Post-visit consultation reports remain distinct from pre-visit supporting documents: delivery and closure require the completed specialist encounter/appointment and the current matching report.

The benchmark uses a custom schema. Diagnosis and clinical test selection are outside scope.


## Public handoff evidence contract

See [ESCALATION_EVIDENCE_CONTRACT.md](ESCALATION_EVIDENCE_CONTRACT.md). The same barrier/read/action table is exposed in every evaluation task under `public_policy.escalation_evidence_contract`. Ordinary blocker codes are not automatically terminal handoff reasons. Grading behavior is unchanged.


## Alternative triggers for one event

An event has one identity and one changes list. Its existing `trigger` may be accompanied by `alternative_triggers`, a list of trigger objects using the same phase/tool/argument-match rules. The first matching trigger fires the event once; later matches do not reapply it, including after a stored session is reopened. Before-operation events run before operation preconditions; their changes persist even when the operation is rejected. Invalid argument-schema requests do not invoke before/after triggers. A schema-valid request can trigger an event before domain validation, including an unknown slot ID.

RR_016/RR_018 use after-find_appointment_slots and before-schedule_appointment alternatives. This closes the pre-discovery booking bypass without requiring a guessed-ID prohibition. No additional read is required solely to satisfy a separate event-occurrence grading gate for these two tasks.
