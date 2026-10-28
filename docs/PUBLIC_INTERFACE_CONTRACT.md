# Public interface and evidence contract

This document defines the public session interface, response envelope, escalation evidence, and evaluator access boundary. Use it with the tool schemas, public policies and external-agent quickstart in the same benchmark version.

## Context and tool calls

`AgentSession.context()` returns `interface_version`, `task_id`, the task's public `agent_input` fields, `public_policy`, `blocker_codes`, and `human_action_codes`. Tool definitions use `name`, `description`, and `input_schema`. Calls must include all required arguments and no additional ones. A session call has the form `session.call(name, arguments, call_id=...)`.

```python
session.call(
    "get_referral",
    {"referral_id": "RR_016_R1"},
    call_id="read-1"
)
```

This is an interface example, not a recorded reviewer interaction.

## Responses

Responses contain `call_id`, `ok`, `data`, `error`, `observation_event_id`, and `simulated_time`. On failure, `data` is `null` and `error` contains `code`, `message`, and `retryable`. On success, `error` is `null`. Observation identifiers support evidence references in later handoffs. Host-maintained logs separately capture operations and environmental changes.

## Escalation fields and evidence

The `escalate` tool requires `referral_id`, `blocker_code`, `evidence_event_ids`, `attempted_action_event_ids`, `reason_unable_to_proceed`, `human_action_code`, and `required_human_action`. The two event-ID fields are arrays; the remaining fields are strings. Recording a ticket does not certify validity: the grader checks the barrier, fields, evidence, and follow-up action.

The shared public policy specifies which observations establish each supported barrier. Directory-based barriers require the complete candidate set, eligibility checks, and relevant document, authorization, or slot observations. Report-unavailability handoffs require report-catalog evidence. Failed reads do not prove absence, and exhausted budgets do not justify escalation. Evidence requirements are public even though outcome labels and grading implementation remain hidden.

## External-agent integration and evaluator boundary

After the evaluator initializes a fresh task environment, give the external agent session context and tool definitions. Its adapter maps each selected tool name and argument object to `session.call`, returns the response unchanged, and retains public observation identifiers. Each new logical call uses a distinct `call_id`.

The evaluator records transcripts and resources, applies declared stopping rules, and invokes the separate grader on trusted state and history. Retain the agent's final response for analysis, but do not use it to determine success. Keep hidden task files, direct database access, event scripts, and grading material outside the agent's accessible context and execution environment. Expose task state only through public tools.

## Companion specifications

- `docs/tool_definitions.json`: complete tool schemas.
- `tasks/eval/` and `tasks/EVALUATION_SPECIFICATIONS.md`: task specifications.
- Task context and `tasks/escalation_evidence_policy.json`: public policies.
- `EXTERNAL_AGENT_QUICKSTART.md`: setup, external-agent integration, grading, and reset.
- `external_agent_example.py`: runnable public-interface example independent of the authors' controllers.
