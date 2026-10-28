# Public escalation evidence contract

This shared contract is included in `context.public_policy.escalation_evidence_contract` for every evaluation task. It does not disclose task-specific outcomes.

## Contract Version

1.0

## Scope

Shared evaluation-task handoff contract. This table does not identify the outcome of any task. Ordinary blockers such as missing_required_document, unsubmitted_complete_packet or report_delivery_failed do not by themselves justify a terminal handoff. The barrier must actually prevent the requested goal.

## Catalog Checks

For each directory-based barrier below, cite find_providers(referral_id) for the complete candidate set, and check_provider_eligibility(referral_id, provider_id) for EVERY returned candidate, including ineligible candidates. Directory results alone do not replace individual eligibility checks. Then perform category-specific reads for every eligible provider.

## Evidence

Cite observation_event_id values from successful actual read responses in evidence_event_ids. All cited IDs must exist in this run and precede ticket creation. Tool names alone, failed reads, inferred absence and fabricated IDs are insufficient. Cite complete results, not only a selected record.

## Freshness

Evidence must describe the current state when the handoff is graded. Directory membership, eligibility facts, provider requirements and the complete relevant document, authorization, report or available-future-slot collections must still match. Derived attached/currently_valid display fields are not compared as stored records. After a change establishes a barrier, obtain a fresh set of all required reads for that barrier, including directory and eligibility checks even for unchanged candidates. Do not reuse pre-change evidence alone. If later actions or time change those facts before grading, refresh evidence; reads themselves advance simulated time.

## Attempts

attempted_action_event_ids may be empty when reads already establish the barrier. Do not manufacture failed mutations. If supplied, IDs must refer to actual mutation calls preceding ticket creation; they do not substitute for required read evidence.

## Handoff

Supply the supported blocker_code and its mapped human_action_code below, nonempty factual reason_unable_to_proceed and required_human_action text, plus evidence_event_ids and attempted_action_event_ids. A tool accepting the ticket is not a guarantee of benchmark success.

## Barrier and action table

| Barrier | Human action | Required reads | Condition |
|---|---|---|---|
| `required_document_unavailable` | `obtain_required_document` | `find_providers`, `check_provider_eligibility`, `get_documents`, `get_provider_requirements` | At least one eligible provider exists, but no eligible provider can receive a complete qualifying packet from the available document catalog. Read get_documents for the referral and get_provider_requirements for every eligible provider. |
| `authorization_denied_human_appeal` | `initiate_human_appeal` | `find_providers`, `check_provider_eligibility`, `check_authorization` | At least one eligible provider exists. Every eligible route requires authorization and has an appeal-only denial matching current coverage, with no currently valid approval permitting recovery. Read check_authorization for the referral; changing providers alone does not resolve this barrier. |
| `no_feasible_slot` | `coordinate_exception` | `find_providers`, `check_provider_eligibility`, `find_appointment_slots` | At least one eligible provider exists. Read find_appointment_slots for every eligible provider; no available future slot satisfies the public scheduling constraints. |
| `no_eligible_provider` | `resolve_provider_access` | `find_providers`, `check_provider_eligibility` | No provider in the complete candidate directory is eligible for this referral. |
| `report_unavailable_or_invalid` | `obtain_valid_report` | `get_consultation_reports` | The specialist encounter is completed and no available current final report matches the target patient, encounter, referral and completed appointment. Read the complete consultation-report collection for the referral. An invalid candidate alone is insufficient. |

Freshness is deliberately conservative: the existing grader can require a complete refresh after a barrier-producing event, including unchanged records. This update documents that contract; it does not implement per-record freshness or alter required-event conditions. Development-only demonstrations retain their existing simpler policy.
