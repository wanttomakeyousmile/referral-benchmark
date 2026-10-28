"""Pure-Python baseline controllers using ONLY the public AgentSession API.

Development-stage implementations. They never load task JSON, grader rules,
reference traces, or database files. The fixed workflow is deliberately simple:
it is not a dependency-memory agent, nor a scored evaluation result.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from .environment import BudgetExceeded
from .catalog import BLOCKERS


def _time(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


class PublicTools:
    def __init__(self, session):
        self.session = session
        self.ctx = session.context()
        self.rid = self.ctx['referral_id']
        self.n = 0
        self.observations = []
        self.errors = []
        self.last_result = None
        self.first_ref = None
        self.last_status = None
        self.ticket_id = None

    def call(self, tool, **args):
        self.n += 1
        try:
            result = self.session.call(tool, args, call_id=f'BASE_{self.n:03d}')
        except BudgetExceeded:
            self.errors.append('BUDGET_EXCEEDED')
            return None
        self.last_result = result
        if not result['ok']:
            self.errors.append(result['error']['code'])
            return None
        data=result['data']
        record=data.get('record',{})
        if tool=='get_referral':
            if self.first_ref is None:self.first_ref=dict(data)
            self.last_status=data.get('status')
        elif tool in {'attach_document','reroute_referral','submit_referral','reconcile_appointment','close_referral'}:
            self.last_status=record.get('status',self.last_status)
        elif tool=='schedule_appointment' and record.get('appointment_id'):self.last_status='scheduled'
        elif tool=='escalate':self.last_status='escalated';self.ticket_id=record.get('ticket_id')
        self.observations.append((tool, result['observation_event_id']))
        return result['data']

    def report(self):
        if self.first_ref is None or self.last_status is None:return None
        return {'schema_version':'1.0',
                'initial_blocker_codes':sorted(set(self.first_ref.get('rejection_codes',[])) & set(BLOCKERS)),
                'final_status_claim':self.last_status,
                'supporting_event_ids':[eid for _,eid in self.observations],
                'escalation_ticket_id':self.ticket_id}

    def ref(self):
        return self.call('get_referral', referral_id=self.rid)

    def get(self, tool):
        return self.call(tool, referral_id=self.rid)


def do_nothing(session):
    """No tools, no final report; the benchmark's grader sanity baseline."""
    session.context()  # only task instructions; no domain reads
    return {'stop_reason': 'do_nothing', 'report': None}


def _doc_matches(doc, rule, ref):
    return (doc.get('available') is True and doc.get('patient_id') == ref['patient_id']
            and doc.get('document_type') == rule['document_type']
            and doc.get('status') in rule['statuses']
            and (rule['linkage'] != 'encounter' or doc.get('encounter_id') == ref['encounter_id'])
            and (rule['linkage'] != 'referral' or ref['referral_id'] in doc.get('related_referral_ids', [])))


def _handle_completed(t, ref):
    reports = t.get('get_consultation_reports')
    if reports is None:
        return False
    # Read-only candidate selection; do not access any hidden task fields.
    good = [x for x in reports['reports'] if x['available'] and x['status'] == 'final'
            and x['patient_id'] == ref['patient_id'] and x['encounter_id'] == ref['encounter_id']
            and x['referral_id'] == ref['referral_id']]
    good = [x for x in good if not any(y.get('supersedes_report_id') == x['report_id']
                                     and y['status'] == 'final' for y in reports['reports'])]
    if not good:
        return False
    report = max(good, key=lambda x: (x['version'], x['report_id']))
    for recipient in ref['allowed_recipient_ids']:
        delivery = t.call('deliver_report', referral_id=t.rid, report_id=report['report_id'], recipient_id=recipient)
        if not delivery:
            return False
        receipt_id = delivery['record']['delivery_id']
        receipt = t.call('get_report_delivery', referral_id=t.rid, delivery_id=receipt_id)
        if not receipt or receipt.get('status') != 'received':
            return False
    return t.call('close_referral', referral_id=t.rid) is not None


def _packet(t, ref, requirement, documents):
    """Attach available matching documents for the current provider. Return readiness."""
    for rule in requirement['required_document_rules']:
        attached = any(x['document_id'] in ref['attached_document_ids'] and _doc_matches(x, rule, ref)
                       for x in documents)
        if attached:
            continue
        matches = sorted((x for x in documents if _doc_matches(x, rule, ref)), key=lambda x: x['document_id'])
        if not matches:
            return False
        if t.call('attach_document', referral_id=t.rid, document_id=matches[0]['document_id']) is None:
            return False
        ref = t.ref()
        if ref is None:
            return False
    return True


def _escalate_missing_document(t):
    # Observe all currently eligible options; no hidden 'escalation_required' label.
    found = t.get('find_providers')
    if found is None:
        return False
    evidence = [eid for name, eid in t.observations if name == 'get_documents']
    for provider in found['providers']:
        elig = t.call('check_provider_eligibility', referral_id=t.rid, provider_id=provider['provider_id'])
        if elig is None:
            return False
        if not elig['eligible']:
            continue
        requirements = t.call('get_provider_requirements', provider_id=provider['provider_id'])
        docs = t.get('get_documents')
        if not requirements or not docs:
            return False
        evidence.extend(eid for name, eid in t.observations[-2:] if name in {'get_documents', 'get_provider_requirements'})
        ref = t.ref()
        if any(not any(_doc_matches(d, rule, ref) for d in docs['documents'])
               for rule in requirements['required_document_rules']):
            continue
        # An eligible path may exist; not safe to escalate for missing documents.
        return False
    if not evidence:
        return False
    response = t.call('escalate', referral_id=t.rid, blocker_code='required_document_unavailable',
                      evidence_event_ids=list(dict.fromkeys(evidence)), attempted_action_event_ids=[],
                      reason_unable_to_proceed='No available qualifying document was found for the eligible provider packet.',
                      human_action_code='obtain_required_document',
                      required_human_action='Obtain and attach the missing required clinical document.')
    return response is not None


def fixed_workflow(session):
    """Inspectable fixed-order administrative workflow with bounded restarts.

    No explicit dependency graph or LLM. Targets straightforward tasks; dynamic
    cases are handled only through an observed rejected submission / fresh reads.
    """
    t = PublicTools(session)
    rid = t.rid
    goal = t.ctx.get('goal', '').lower()
    want_booking = ('schedul' in goal or 'book' in goal or 'appointment' in goal)
    ref = t.ref()
    if not ref:
        return {'stop_reason': 'read_failed', 'report': t.report(), 'errors': t.errors}
    if ref['status'] in {'closed', 'escalated'}:
        return {'stop_reason': 'terminal', 'report': t.report(), 'errors': t.errors}
    if ref['status'] == 'completed':
        done = _handle_completed(t, ref)
        return {'stop_reason': 'completed_report' if done else 'report_unresolved', 'report': t.report(), 'errors': t.errors}
    appointments = t.get('get_appointments')
    if appointments and appointments['appointments']:
        if ref['status'] == 'scheduled':
            return {'stop_reason': 'already_scheduled', 'report': t.report(), 'errors': t.errors}
        for ap in appointments['appointments']:
            if ap['status'] == 'scheduled':
                result = t.call('reconcile_appointment', referral_id=rid, appointment_id=ap['appointment_id'])
                if result is not None:
                    return {'stop_reason': 'reconciled', 'report': t.report(), 'errors': t.errors}
    # One initial provider followed by at most two reroutes. No access to task IDs.
    used_providers = set()
    for _ in range(3):
        ref = t.ref()
        if ref is None:
            break
        provider_id = ref['provider_id']
        used_providers.add(provider_id)
        requirement = t.call('get_provider_requirements', provider_id=provider_id)
        docs = t.get('get_documents')
        if not requirement or not docs:
            break
        packet_ready = _packet(t, ref, requirement, docs['documents'])
        if not packet_ready:
            if _escalate_missing_document(t):
                return {'stop_reason': 'human_handoff', 'report': t.report(), 'errors': t.errors}
            break
        result = t.call('submit_referral', referral_id=rid)
        if result is None:
            break
        ref = t.ref()
        if ref is None:
            break
        if ref['status'] == 'rejected':
            candidates = t.get('find_providers')
            if candidates is None:
                break
            moved = False
            for provider in sorted(candidates['providers'], key=lambda x: x['provider_id']):
                pid = provider['provider_id']
                if pid in used_providers:
                    continue
                eligibility = t.call('check_provider_eligibility', referral_id=rid, provider_id=pid)
                if eligibility and eligibility['eligible'] and t.call('reroute_referral', referral_id=rid, provider_id=pid) is not None:
                    moved = True
                    break
            if moved:
                continue
            break
        if ref['status'] != 'accepted':
            break
        if not want_booking:
            return {'stop_reason': 'accepted', 'report': t.report(), 'errors': t.errors}
        auth = t.get('check_authorization')
        if auth is None:
            break
        if auth['required'] and not any(x['currently_valid'] for x in auth['authorizations']):
            if t.call('request_authorization', referral_id=rid) is None:
                break
            auth = t.get('check_authorization')
            if not auth or not any(x['currently_valid'] for x in auth['authorizations']):
                break
        slots = t.call('find_appointment_slots', referral_id=rid, provider_id=ref['provider_id'])
        if slots is None:
            break
        cons = slots['constraints']
        candidates = [x for x in slots['slots'] if
                      ('earliest' not in cons or _time(x['start_at']) >= _time(cons['earliest']))
                      and ('latest' not in cons or _time(x['start_at']) <= _time(cons['latest']))
                      and ('allowed_slot_ids' not in cons or x['slot_id'] in cons['allowed_slot_ids'])]
        for slot in sorted(candidates, key=lambda x: (x['start_at'], x['slot_id'])):
            booked = t.call('schedule_appointment', referral_id=rid, slot_id=slot['slot_id'])
            if booked is not None:
                return {'stop_reason': 'booked', 'report': t.report(), 'errors': t.errors}
        break
    return {'stop_reason': 'workflow_unresolved', 'report': t.report(), 'errors': t.errors}

BASELINES = {'do_nothing': do_nothing, 'fixed_workflow': fixed_workflow}
