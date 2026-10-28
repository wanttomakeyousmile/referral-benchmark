# RR_016 exact worked example

This scripted demonstration reproduces one valid solution using only public context and observed records in the demonstration function. It is not a model baseline or independent human review. The host loads the task and grades the resulting trusted exports separately. Keep this answer-bearing example and all trusted exports outside scored-agent access and withhold them from blind reviewers until initial judgments are saved.

## Source and reproduction


From the extracted benchmark directory run:

```sh
python3 worked_example_rr016.py --output ../rr016_reproduction
python3 -m unittest discover -s tests -v
```

Use a new output directory. Each execution creates a new runtime run_id, so that identifier differs from the bundled evidence. Public transcripts, final states and grader verdicts reproduce exactly. Python 3.10+ and the standard library are sufficient. Each branch begins from a fresh environment. The reproduction script asserts the expected verdicts and identical three-call transcript prefix.

## Exact public goal

Recover this referral and establish a valid appointment within its stated scheduling constraints. If observations establish a declared human-only barrier that prevents this goal, create an evidence-supported human handoff under the public escalation policy; budget exhaustion alone does not justify escalation.

Referral ID: `RR_016_R1`. Full public context, policies and tool schemas are in `success/public_context.json`. No hidden event or evaluation fields are passed to the demonstration function.

## Exact calls and selected response fields

The JSON below contains literal selected fields from the recorded responses, not entire responses. Omitted fields are retained in each branch's public_transcript.json. Provider ID comes from get_referral; slot ID comes from find_appointment_slots. Slot selection checks the publicly observed scheduling window.

### Call 1: get_referral

Arguments:
```json
{
  "referral_id": "RR_016_R1"
}
```
Selected response fields:
```json
{
  "data": {
    "provider_id": "RR_016_CARD_A",
    "status": "accepted"
  }
}
```

### Call 2: find_appointment_slots

Arguments:
```json
{
  "referral_id": "RR_016_R1",
  "provider_id": "RR_016_CARD_A"
}
```
Selected response fields:
```json
{
  "data": {
    "slots": [
      {
        "available": true,
        "end_at": "2026-09-10T10:30:00Z",
        "provider_id": "RR_016_CARD_A",
        "slot_id": "RR_016_SLOT_A",
        "start_at": "2026-09-10T10:00:00Z"
      }
    ]
  }
}
```

### Call 3: schedule_appointment

Arguments:
```json
{
  "referral_id": "RR_016_R1",
  "slot_id": "RR_016_SLOT_A"
}
```
Selected response fields:
```json
{
  "ok": false,
  "error": {
    "code": "AUTHORIZATION_INVALID",
    "message": "Authorization invalid",
    "retryable": false
  }
}
```

### Call 4: get_coverage

Arguments:
```json
{
  "referral_id": "RR_016_R1"
}
```
Selected response fields:
```json
{
  "data": {
    "authoritative": {
      "coverage_version": 2,
      "insurance_plan_id": "PLAN_B",
      "patient_id": "RR_016_P1"
    }
  }
}
```

### Call 5: check_authorization

Arguments:
```json
{
  "referral_id": "RR_016_R1"
}
```
Selected response fields:
```json
{
  "data": {
    "authorizations": [
      {
        "authorization_id": "RR_016_AUTH1",
        "coverage_version": 1,
        "decision_code": "approved",
        "human_appeal_required": false,
        "insurance_plan_id": "PLAN_A",
        "provider_id": "RR_016_CARD_A",
        "referral_id": "RR_016_R1",
        "status": "invalidated",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_until": "2026-10-01T00:00:00Z",
        "currently_valid": false
      }
    ]
  }
}
```

### Call 6: request_authorization

Arguments:
```json
{
  "referral_id": "RR_016_R1"
}
```
Selected response fields:
```json
{
  "data": {
    "record": {
      "authorization_id": "AUTHORIZATIONS_0001",
      "referral_id": "RR_016_R1",
      "provider_id": "RR_016_CARD_A",
      "insurance_plan_id": "PLAN_B",
      "coverage_version": 2,
      "status": "approved",
      "valid_from": "2026-09-01T09:06:00Z",
      "valid_until": "2026-10-01T09:06:00Z",
      "human_appeal_required": false,
      "decision_code": "approved"
    }
  }
}
```

### Call 7: schedule_appointment

Arguments:
```json
{
  "referral_id": "RR_016_R1",
  "slot_id": "RR_016_SLOT_A"
}
```
Selected response fields:
```json
{
  "data": {
    "record": {
      "appointment_id": "APPOINTMENTS_0002",
      "referral_id": "RR_016_R1",
      "patient_id": "RR_016_P1",
      "provider_id": "RR_016_CARD_A",
      "slot_id": "RR_016_SLOT_A",
      "status": "scheduled",
      "booked_at": "2026-09-01T09:07:00Z",
      "acceptance_id": "RR_016_ACC0",
      "authorization_id": "AUTHORIZATIONS_0001"
    }
  }
}
```

## Pass and fail conditions

The success branch makes seven calls and ends with a scheduled appointment. All six declared predicates pass: packet_complete, provider_eligible, acceptance_valid, authorization_valid, appointment_valid and no_duplicate_appointment. Final-state errors, hard violations, failed constraints and missing required events are empty.

The failure branch stops after the identical third response, AUTHORIZATION_INVALID. authorization_valid and appointment_valid are false, so the scheduled outcome fails. There are no hard violations. A rejected booking is not itself an executed prohibited booking. The trusted operation snapshots confirm that the rejection creates no appointment.

The coverage event fires after slot discovery. RR_016 has no separate required-event success gate. Its valid state, outcome and action history still matter. This sequence is one valid solution, not a mandatory read or action order and not a claim of exhaustive path coverage.

## Evidence files

Each public branch contains public_context.json, public_transcript.json and grade.json. Run the reproduction script to generate the full trusted state, history and runtime exports in a separate directory. The public transcript contains only actual tool calls and responses. Grader output and host exports are evaluator material. SQLite working databases are omitted because the reproduction script recreates them.
