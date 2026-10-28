# Referral recovery evaluation specifications

Specifications for the 20 evaluation tasks, their task contracts, and grading predicates.

## Usage

From the extracted project root, with Python 3.10 or newer:

```sh
python3 tasks/validate_evaluation_specs.py
python3 tasks/validate_recovery_paths.py
python3 -m unittest discover -s tests -v
```

Rebuild the authored specifications, if needed:

```sh
python3 tasks/make_evaluation_cases.py
```

The package includes the environment and independent grader. Structural validation prints its summary; use `--output PATH` to save detailed structural/load checks. `../docs/validation_results.json` records actual fixture
execution. The JSON schema now includes canonical record fields; Python validation
also checks records, references and blocker/human-action vocabularies without optional
dependencies. A full third-party JSON Schema pass is optional and separately reported.

## Task contract

Each file contains `schema_version`, unique `task_id`, metadata with difficulty, capability tags and development distinction, public `agent_input` and `public_policy`, a complete environment with canonical record collections and deterministic events, a hidden `evaluation` fragment, and a trusted `authoring` fragment with a reference outline, negative checks and implementation dependencies.

Only `AgentSession.context()`, tool definitions and tool results may be exposed to agents. Do not serialize task files into prompts: `evaluation`, `authoring`, future events and simulator outcomes are private. Initial blocker labels describe starting state; event-induced blockers are not retroactively initial labels.

Record IDs are prefixed by task ID. The 20 cases have 7 easy, 7 medium and 6 hard labels; 5 require escalation. Difficulty labels are provisional author-assigned metadata. DEV_001–DEV_004 remain separate. Evaluation cases share workflow families and record structure with development; this is not an unseen-domain or independent-blind test suite.

## Predicate specification for the independent grader

Names below are implemented in `referral_recover/grader.py`, independently of Engine helpers. Grading must use trusted state and logs, not environment helper results alone, agent claims, or a reference-path string. An allowed outcome passes only if its terminal status, predicates, global rules and task constraints all hold. `required_event_ids`, when present, must occur in the trusted event history. This applies to scenarios where the disruption is essential to the allowed outcome (including RR_020). RR_017 is an exposure-conditional disruption: booking a different compliant slot without attempting SLOT_A is valid and must not require SLOT_LOST to fire. When SLOT_A is attempted, the environment still fires SLOT_LOST and rejects that booking. RR_015's invalidation is caused by rerouting rather than an external event.

| Predicate | Required meaning |
|---|---|
| packet_complete | Every current-provider document rule has at least one attached available document satisfying type, allowed status and linkage; attached evidence has correct patient identity. |
| provider_eligible | Current provider matches fixed specialty, accepts authoritative current coverage, and is accepting referrals. Apply any public provider restriction too. |
| acceptance_valid | Referral references an active acceptance for current provider, current requirements version and current qualifying document versions; packet is complete. |
| authorization_valid | If required, an approved authorization matches referral, provider, current plan/coverage version and valid time interval; use visit-time validity only when the task declares it. |
| appointment_valid | Exactly one scheduled appointment links the correct patient/referral/provider, a reserved slot within public constraints, and legitimate acceptance/authorization evidence at booking. Current required prerequisites also hold. |
| no_duplicate_appointment | At most one active scheduled appointment for the referral; duplicate creation in history is a hard violation even if later removed. |
| current_report_matches | An available final report matches patient, encounter, referral and completed appointment; no applicable current successor makes it obsolete. |
| all_required_receipts | Every allowed recipient has a received delivery with a real receipt for the current matching report/version. Failed or pending deliveries do not qualify. |
| closure_valid | Completed encounter and appointment, current matching report and all required receipts exist; referral is closed. |
| escalation_ticket_valid | A real ticket links the referral, has a nonempty barrier/reason/action and valid evidence event references. |
| barrier_true | Task-specific finite barrier definition in `evaluation.escalation` is true in trusted state; no permitted recovery route remains in the declared finite catalog. |
| evidence_supports_barrier | Successful logged observations cover the barrier records and relevant candidate set. A tool-name match alone is insufficient. For event-induced barriers, evidence must reflect the event. Failed reads never establish absence. |
| human_action_allowed | Ticket's structured `human_action_code` belongs to the task's allowed code set. The tool and record require this structured field. |

Global rules version 1.0 refers to `docs/INTERFACE_AND_GRADING.md`: preserve patient and clinical intent; reject executed unavailable/wrong evidence attachment, invalid routing, booking without valid prerequisites, duplicates, wrong/obsolete reports, unauthorized recipients and receipt-free closure. Global rules cannot be weakened by omitting task-specific constraints. Distinguish blocked attempts from executed changes and environment-triggered changes from agent mutations. Repaired executed violations still fail.

Additional task constraints:
- `preserve_existing_appointment`: RR_012 must retain its specified appointment identity and booking evidence and reconcile referral status; replacing it or creating another appointment fails.
- `provider_unchanged` remains a supported general constraint, but RR_008 no longer uses it. CARD_B is out of network; the complete directory and appeal-only denial make human intervention necessary.

## Scenario rules

- All five escalation cases use canonical blocker codes and a required structured human action.
- RR_007 and RR_008 require directory discovery and eligibility evidence for every candidate.
- RR_014 checks slots for every eligible provider against the public deadline.
- RR_019 requires fresh post-event eligibility evidence for the complete directory.
- RR_017 loses SLOT_A immediately before an attempted booking of that slot.
- RR_020 withdraws the observed report immediately before its attempted delivery;
  its escalation requires fresh report inspection after withdrawal.
- Public `human_action_codes` lists the same full category vocabulary in every task,
  without exposing which action is correct for the task.

### Encounter context and document linkage

For pre-visit recovery tasks, encounter-linked supporting documents represent pre-visit workup associated with the planned specialist encounter. A final supporting document can therefore be linked to a planned encounter without implying that the specialist visit has occurred. This is the intended meaning of the current task records; it does not introduce an earlier completed diagnostic encounter.

- `linkage: encounter` requires `document.encounter_id == referral.encounter_id`.
- `linkage: referral` requires `referral.referral_id in document.related_referral_ids`.
- Both rules also require matching patient identity, an available document, the required document type and an allowed status.
- The linkage rule applies per provider requirement, rather than imposing same-encounter matching on every document.
- Post-visit consultation reports remain distinct from pre-visit supporting documents: delivery and closure require the completed specialist encounter/appointment and the current matching report.

The benchmark uses a custom schema. Diagnosis and clinical test selection are outside scope.

### RR_001 intake requirement

RR_001 uses `RR_001_PFT1` for its `pulmonary_function_report`. This is an authored, synthetic provider-specific intake requirement, not a general cardiology guideline. Clinical appropriateness and referral intent are fixed. The agent finds and attaches an existing qualifying document; diagnosis and clinical test selection are outside scope.


## RR_003 alternative paths

The reference outline is one valid recovery, not a required action sequence. An executed 11-call alternative uses observed provider/document/slot IDs to reroute before submitting the repaired packet and is accepted. INTAKE_CHANGE is triggered by a complete submission for the referral, regardless of the current provider. Therefore, encountering rejection from the original provider before rerouting is not mandatory. Describe the case as supporting repair, routing and dependency revalidation; do not claim every successful trajectory demonstrates reactive recovery from original-provider rejection.


## RR_016/RR_018 event progression

Their coverage/expiry events fire after slot discovery or immediately before the first booking attempt, whichever occurs first. Each event fires once. Booking checks use the updated state. An authorization-invalid booking creates no appointment; the agent may inspect, repair and retry. The independent required-event success gate is removed for these two tasks. Existing RR_003/RR_019/RR_020 requirements remain in force.
