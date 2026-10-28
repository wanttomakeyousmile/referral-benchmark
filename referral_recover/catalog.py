"""Provider-neutral tool declarations; no evaluator metadata belongs here."""
READS = {
    'get_referral': ('referral_id',),
    'get_coverage': ('referral_id',),
    'get_documents': ('referral_id',),
    'get_provider_requirements': ('provider_id',),
    'find_providers': ('referral_id',),
    'check_provider_eligibility': ('referral_id', 'provider_id'),
    'check_authorization': ('referral_id',),
    'find_appointment_slots': ('referral_id', 'provider_id'),
    'get_appointments': ('referral_id',),
    'get_consultation_reports': ('referral_id',),
    'get_report_delivery': ('referral_id', 'delivery_id'),
}
MUTATIONS = {
    'attach_document': ('referral_id', 'document_id'),
    'submit_referral': ('referral_id',),
    'reroute_referral': ('referral_id', 'provider_id'),
    'request_authorization': ('referral_id',),
    'schedule_appointment': ('referral_id', 'slot_id'),
    'reconcile_appointment': ('referral_id', 'appointment_id'),
    'deliver_report': ('referral_id', 'report_id', 'recipient_id'),
    'close_referral': ('referral_id',),
    'escalate': ('referral_id', 'blocker_code', 'evidence_event_ids',
                 'attempted_action_event_ids', 'reason_unable_to_proceed', 'human_action_code', 'required_human_action'),
}
TOOLS = {**READS, **MUTATIONS}
BLOCKERS = ['missing_required_document', 'unsubmitted_complete_packet', 'scheduling_pending',
    'missing_authorization', 'required_document_unavailable', 'authorization_denied_human_appeal',
    'provider_not_accepting', 'coverage_conflict', 'document_selection_required',
    'appointment_record_mismatch', 'report_delivery_pending', 'report_delivery_failed',
    'no_feasible_slot', 'authorization_expired', 'report_unavailable_or_invalid', 'no_eligible_provider']
HUMAN_ACTION_CODES = ['obtain_required_document', 'initiate_human_appeal', 'coordinate_exception', 'resolve_provider_access', 'obtain_valid_report']
PREMATURE = {'PACKET_INCOMPLETE', 'REFERRAL_NOT_ACCEPTED', 'AUTHORIZATION_INVALID',
             'REPORT_NOT_FINAL', 'APPOINTMENT_NOT_COMPLETED', 'CLOSURE_REQUIREMENTS_UNMET'}
DESCRIPTIONS = {
    'get_referral': 'Inspect referral records, linked IDs, and public scheduling/delivery policies.',
    'get_coverage': 'Read authoritative coverage and source-versioned records.',
    'get_documents': 'List discoverable document metadata and attachment status.',
    'get_provider_requirements': 'Read current provider documentation and authorization requirements.',
    'find_providers': 'List directory candidates for the authorized specialty; check eligibility separately.',
    'check_provider_eligibility': 'Check network, specialty, and intake eligibility.',
    'check_authorization': 'Inspect authorization records and current applicability.',
    'find_appointment_slots': 'List available provider slots and patient constraints.',
    'get_appointments': 'Inspect linked appointments, including existing bookings.',
    'get_consultation_reports': 'List report candidates with linkage, version, and status.',
    'get_report_delivery': 'Inspect delivery status and receipt for a specific delivery.',
    'attach_document': 'Attach an available qualifying document; duplicate attachment is a no-op.',
    'submit_referral': 'Submit a complete packet for acceptance; rejection is a domain outcome.',
    'reroute_referral': 'Change to an eligible provider; invalidates prior acceptance and provider authorization.',
    'request_authorization': 'Request authorization; approved, denied, and pending are distinct outcomes.',
    'schedule_appointment': 'Book a compliant slot after acceptance and required authorization.',
    'reconcile_appointment': 'Link an existing valid appointment without creating a duplicate.',
    'deliver_report': 'Deliver a current matching final report to an authorized recipient; does not close.',
    'close_referral': 'Close only after completed visit and required current report receipts.',
    'escalate': 'Record an evidence-linked human handoff. This does not certify that escalation is justified.',
}

def tool_definitions():
    return [{'name': n, 'description': DESCRIPTIONS[n], 'input_schema': {
        'type': 'object', 'properties': {k: ({'type': 'array', 'items': {'type': 'string'}}
            if k.endswith('_event_ids') else {'type': 'string', 'enum': BLOCKERS} if k == 'blocker_code' else {'type': 'string', 'enum': HUMAN_ACTION_CODES} if k == 'human_action_code' else {'type': 'string', 'minLength': 1}) for k in keys},
        'required': list(keys), 'additionalProperties': False}} for n, keys in TOOLS.items()]
