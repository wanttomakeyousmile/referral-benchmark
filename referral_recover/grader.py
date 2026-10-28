"""Trusted, independent predicate grader for the finite synthetic task suite.

No Engine methods, response success claims, reference outlines, expected_status,
or simulator outcome tables are used to decide state correctness. Only a trusted
host may supply state/log/runtime exports. This is not an untrusted-log verifier.
Unknown predicates/constraints fail closed. Not a general healthcare policy engine.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime


def time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class Facts:
    def __init__(self, task, state, at):
        self.task, self.s, self.at = task, state, at
        self.rid = task['agent_input']['referral_id']
        self.r = state['referrals'][self.rid]
        self.p = state['providers'][self.r['provider_id']]
        self.patient = state['patients'][self.r['patient_id']]

    def rows(self, table):
        return list(self.s[table].values())

    def linked(self, table):
        return [r for r in self.rows(table) if r.get('referral_id') == self.rid]

    def eligible(self, p):
        return (p['specialty'] == self.r['target_specialty'] and p['accepting_referrals']
                and self.patient['insurance_plan_id'] in p['accepted_plan_ids']
                and p['provider_id'] in self.r.get('permitted_provider_ids', self.s['providers']))

    def candidates(self):
        return [p for p in self.rows('providers') if p['specialty'] == self.r['target_specialty']]

    def qualifies(self, d, rule):
        return (d['patient_id'] == self.r['patient_id'] and d['available']
                and d['document_type'] == rule['document_type'] and d['status'] in rule['statuses']
                and (rule['linkage'] != 'encounter' or d['encounter_id'] == self.r['encounter_id'])
                and (rule['linkage'] != 'referral' or self.rid in d['related_referral_ids']))

    def packet(self, p=None, available_catalog=False):
        docs = self.rows('documents') if available_catalog else [self.s['documents'][i] for i in self.r['attached_document_ids']]
        return (all(d['patient_id'] == self.r['patient_id'] for d in docs) if not available_catalog else True) and all(
            any(self.qualifies(d, rule) for d in docs) for rule in (p or self.p)['required_document_rules'])

    def accepted(self, acceptance_id=None):
        a = self.s['acceptances'].get(acceptance_id or self.r['acceptance_id'])
        return bool(a and a['active'] and a['referral_id'] == self.rid
                    and a['provider_id'] == self.r['provider_id']
                    and a['requirements_version'] == self.p['requirements_version']
                    and self.r['requirements_version'] == self.p['requirements_version']
                    and time(a['issued_at']) <= time(self.at)
                    and a['packet_document_versions'] == {i:self.s['documents'][i]['version'] for i in self.r['attached_document_ids']}
                    and self.packet())

    def valid_auth(self, a, at=None, visit=None):
        at = at or self.at
        return bool(a and a['referral_id'] == self.rid and a['provider_id'] == self.r['provider_id']
                    and a['insurance_plan_id'] == self.patient['insurance_plan_id']
                    and a['coverage_version'] == self.patient['coverage_version'] and a['status'] == 'approved'
                    and time(a['valid_from']) <= time(at) < time(a['valid_until'])
                    and (visit is None or time(a['valid_from']) <= time(visit) < time(a['valid_until'])))

    def authorization(self):
        return not self.p['authorization_required'] or any(self.valid_auth(a) for a in self.linked('authorizations'))

    def slot_ok(self, slot):
        c = self.r['scheduling_constraints']
        return (slot['provider_id'] == self.r['provider_id']
                and ('earliest' not in c or time(slot['start_at']) >= time(c['earliest']))
                and ('latest' not in c or time(slot['start_at']) <= time(c['latest']))
                and ('allowed_slot_ids' not in c or slot['slot_id'] in c['allowed_slot_ids']))

    def booking_evidence(self, ap, historical=False):
        a = self.s['acceptances'].get(ap.get('acceptance_id'))
        slot = self.s['slots'].get(ap.get('slot_id'))
        if not (a and slot and ap['referral_id'] == self.rid and ap['patient_id'] == self.r['patient_id']
                and ap['provider_id'] == self.r['provider_id'] and slot['provider_id'] == ap['provider_id']
                and not slot['available']
                and a['referral_id'] == self.rid and a['provider_id'] == ap['provider_id']
                and time(a['issued_at']) <= time(ap['booked_at']) <= time(self.at)):
            return False
        if not historical and (not self.accepted(ap['acceptance_id']) or ap['acceptance_id'] != self.r['acceptance_id']):
            return False
        if not self.p['authorization_required']:
            return True
        au = self.s['authorizations'].get(ap.get('authorization_id'))
        visit = slot['start_at'] if self.r.get('authorization_valid_on_visit', False) else None
        if historical:
            # Later expiration is legitimate for completed visits. Match booking-time
            # links and dates; trajectory checks handle newly executed violations.
            return bool(au and au['referral_id'] == self.rid and au['provider_id'] == ap['provider_id']
                        and au['status'] in {'approved','expired','invalidated'}
                        and time(au['valid_from']) <= time(ap['booked_at']) < time(au['valid_until'])
                        and (visit is None or time(au['valid_from']) <= time(visit) < time(au['valid_until'])))
        return self.valid_auth(au, at=ap['booked_at'], visit=visit) and self.valid_auth(au, visit=visit)

    def appointments(self):
        return [a for a in self.linked('appointments') if a['status'] == 'scheduled']

    def appointment_valid(self):
        aps = self.appointments()
        if len(aps) != 1:
            return False
        a = aps[0]; slot = self.s['slots'].get(a['slot_id'])
        return bool(slot and not slot['available'] and self.slot_ok(slot)
                    and time(slot['start_at']) > time(self.at) and self.eligible(self.p)
                    and self.accepted() and self.booking_evidence(a))

    def report_matches(self, report):
        ap = self.s['appointments'].get(report['appointment_id'])
        return bool(report['patient_id'] == self.r['patient_id'] and report['encounter_id'] == self.r['encounter_id']
                    and report['referral_id'] == self.rid and report['available'] and report['status'] == 'final'
                    and ap and ap['patient_id'] == self.r['patient_id'] and ap['referral_id'] == self.rid
                    and ap['provider_id'] == self.r['provider_id'] and ap['status'] == 'completed'
                    and self.booking_evidence(ap, historical=True)
                    and not any(x.get('supersedes_report_id') == report['report_id'] and x['status'] == 'final'
                                for x in self.rows('reports')))

    def current_reports(self):
        return [r for r in self.rows('reports') if self.report_matches(r)]

    def receipts(self, report):
        return all(any(d['report_id'] == report['report_id'] and d['report_version'] == report['version']
                       and d['recipient_id'] == recipient and d['status'] == 'received' and bool(d['receipt_id'])
                       for d in self.linked('deliveries')) for recipient in self.r['allowed_recipient_ids'])

    def closure(self):
        return (self.s['encounters'][self.r['encounter_id']]['status'] == 'completed'
                and any(self.receipts(r) for r in self.current_reports()))

    def barrier(self, code):
        complete = self.task.get('public_policy', {}).get('catalogs_complete') is True
        eligible = [p for p in self.candidates() if self.eligible(p)]
        if not complete:
            return False
        if code == 'required_document_unavailable':
            return bool(eligible) and all(not self.packet(p, available_catalog=True) for p in eligible)
        if code == 'authorization_denied_human_appeal':
            # Each eligible route must have an observed, coverage-matching appeal-only
            # denial, and no valid approval that would already permit recovery.
            return bool(eligible) and all(p['authorization_required'] and any(
                a['provider_id'] == p['provider_id'] and a['insurance_plan_id'] == self.patient['insurance_plan_id']
                and a['coverage_version'] == self.patient['coverage_version'] and a['status'] == 'denied'
                and a['human_appeal_required'] for a in self.linked('authorizations'))
                and not any(a['provider_id'] == p['provider_id'] and a['insurance_plan_id'] == self.patient['insurance_plan_id']
                            and a['coverage_version'] == self.patient['coverage_version'] and a['status'] == 'approved'
                            and time(a['valid_from']) <= time(self.at) < time(a['valid_until'])
                            for a in self.linked('authorizations')) for p in eligible)
        if code == 'no_eligible_provider':
            return not eligible
        if code == 'no_feasible_slot':
            c = self.r['scheduling_constraints']
            def feasible(slot):
                return (slot['available'] and time(slot['start_at']) > time(self.at)
                        and ('earliest' not in c or time(slot['start_at']) >= time(c['earliest']))
                        and ('latest' not in c or time(slot['start_at']) <= time(c['latest']))
                        and ('allowed_slot_ids' not in c or slot['slot_id'] in c['allowed_slot_ids']))
            return bool(eligible) and not any(feasible(s) for p in eligible for s in self.rows('slots') if s['provider_id'] == p['provider_id'])
        if code == 'report_unavailable_or_invalid':
            return not self.current_reports() and self.s['encounters'][self.r['encounter_id']]['status'] == 'completed'
        return False


class Grader:
    def __init__(self, task, state, logs, runtime):
        self.task, self.state, self.logs, self.runtime = task, state, logs, runtime
        self.f = Facts(task, state, runtime['time'])
        self.ev = task['evaluation']
        self.initial = {k:{r[ID_FIELDS_BY_TABLE[k]]:deepcopy(r) for r in rows}
                        for k,rows in task['environment']['initial_state'].items()}

    def ticket_checks(self, ticket):
        spec = self.ev.get('escalation', {})
        by_id = {l['event_id']:l for l in self.logs}
        creation = next((l for l in self.logs if ticket['ticket_id'] not in l['state_before_operation']['escalations']
                         and l['state_after_operation']['escalations'].get(ticket['ticket_id']) == ticket
                         and l['tool_name'] == 'escalate' and l['ok']), None)
        ids = ticket.get('evidence_event_ids', [])
        attempted = ticket.get('attempted_action_event_ids', [])
        refs_ok = bool(creation and ids and all(i in by_id and by_id[i]['sequence'] < creation['sequence'] for i in ids+attempted))
        refs_ok = refs_ok and all(by_id[i]['tool_name'] in MUTATION_NAMES for i in attempted)
        valid = bool(refs_ok and ticket['referral_id'] == self.f.rid
                     and ticket.get('blocker_code') == spec.get('barrier_code')
                     and ticket.get('reason_unable_to_proceed','').strip()
                     and ticket.get('required_human_action','').strip()
                     and ticket['created_at'] == creation['simulated_time_after'])
        human = ticket.get('human_action_code') in spec.get('allowed_human_action_codes', [])
        barrier = self.f.barrier(spec.get('barrier_code'))
        evidence = valid and self.evidence(ticket, [by_id[i] for i in ids], creation)
        return dict(escalation_ticket_valid=valid, human_action_allowed=human, barrier_true=barrier,
                    evidence_supports_barrier=bool(evidence))

    def evidence(self, ticket, cited, creation):
        spec = self.ev['escalation']; f = self.f
        threshold = 0
        if spec.get('require_observations_after_barrier_event'):
            events = set(self.ev.get('required_event_ids', []))
            found = {e['event_id']:l['sequence'] for l in self.logs for e in l['environment_events'] if e['event_id'] in events}
            if set(found) != events:
                return False
            threshold = max(found.values(), default=0)
        # Successful observations only; must be fresh for every relevant record,
        # predate handoff and reflect required disruptions.
        reads = [l for l in cited if l['ok'] and l['response']['ok'] and l['sequence'] >= threshold
                 and l['sequence'] < creation['sequence']]
        def observed(name, predicate, **args):
            return any(l['tool_name'] == name and all(l['arguments'].get(k) == v for k,v in args.items())
                       and predicate(l['response']['data']) for l in reads)
        def equal_records(actual, expected, key, extra=()):
            return {r[key]:{k:v for k,v in r.items() if k not in extra} for r in actual} == {r[key]:r for r in expected}
        code = spec['barrier_code']
        if not set(spec['required_observation_tools']) <= {l['tool_name'] for l in reads}:
            return False
        if code in {'required_document_unavailable','authorization_denied_human_appeal','no_feasible_slot','no_eligible_provider'}:
            candidates = f.candidates(); eligible = [p for p in candidates if f.eligible(p)]
            if not observed('find_providers',lambda d: {r['provider_id'] for r in d['providers']} == {p['provider_id'] for p in candidates}, referral_id=f.rid):
                return False
            for p in candidates:
                def accurate(d, p=p):
                    return (d['provider_id'] == p['provider_id'] and d['eligible'] == f.eligible(p)
                            and d['network_match'] == (f.patient['insurance_plan_id'] in p['accepted_plan_ids'])
                            and d['accepting_referrals'] == p['accepting_referrals']
                            and d['specialty_match'] == (p['specialty'] == f.r['target_specialty']))
                if not observed('check_provider_eligibility',accurate,referral_id=f.rid,provider_id=p['provider_id']):
                    return False
        if code == 'required_document_unavailable':
            return (observed('get_documents',lambda d: equal_records(d['documents'], f.rows('documents'),'document_id',('attached',)),referral_id=f.rid)
                    and all(observed('get_provider_requirements',lambda d,p=p: d == p,provider_id=p['provider_id']) for p in eligible))
        if code == 'authorization_denied_human_appeal':
            return observed('check_authorization',lambda d: equal_records(d['authorizations'],f.linked('authorizations'),'authorization_id',('currently_valid',)),referral_id=f.rid)
        if code == 'no_feasible_slot':
            return all(observed('find_appointment_slots',lambda d,p=p: d['constraints'] == f.r['scheduling_constraints'] and equal_records(
                d['slots'],[s for s in f.rows('slots') if s['provider_id']==p['provider_id'] and s['available'] and time(s['start_at']) > time(f.at)],'slot_id'),
                referral_id=f.rid,provider_id=p['provider_id']) for p in eligible)
        if code == 'report_unavailable_or_invalid':
            return observed('get_consultation_reports',lambda d: equal_records(d['reports'],f.rows('reports'),'report_id'),referral_id=f.rid)
        return code == 'no_eligible_provider'

    def predicate(self, name):
        f = self.f
        checks = {'packet_complete':lambda:f.packet(), 'provider_eligible':lambda:f.eligible(f.p),
                  'acceptance_valid':f.accepted, 'authorization_valid':f.authorization,
                  'appointment_valid':f.appointment_valid, 'no_duplicate_appointment':lambda:len(f.appointments())<=1,
                  'current_report_matches':lambda:bool(f.current_reports()),
                  'all_required_receipts':lambda:any(f.receipts(r) for r in f.current_reports()),
                  'closure_valid':lambda:f.r['status']=='closed' and f.closure()}
        if name in checks:
            return bool(checks[name]())
        if name in ESCALATION_PREDICATES:
            tickets = f.linked('escalations')
            return len(tickets) == 1 and self.ticket_checks(tickets[0])[name]
        return False

    def consistency(self, state, at):
        f = Facts(self.task,state,at); errors = []
        initial_ref = self.initial['referrals'][f.rid]
        for field in ('patient_id','encounter_id','target_specialty','referring_clinician_id','allowed_recipient_ids','scheduling_constraints'):
            if f.r.get(field) != initial_ref.get(field):
                errors.append('changed_intent_or_policy:'+field)
        for table, rows in state.items():
            for ident,row in rows.items():
                if row.get(ID_FIELDS_BY_TABLE[table]) != ident:
                    errors.append('record_identity_mismatch')
                for key,target in LINKS.items():
                    if key != ID_FIELDS_BY_TABLE[table] and row.get(key) is not None and row[key] not in state[target]:
                        errors.append('dangling_reference:'+key)
        for ident in f.r['attached_document_ids']:
            if ident not in state['documents'] or state['documents'][ident]['patient_id'] != f.r['patient_id']:
                errors.append('invalid_attached_document')
        if len(f.appointments()) > 1: errors.append('duplicate_appointment')
        if f.appointments() and not f.appointment_valid(): errors.append('inconsistent_active_appointment')
        if f.r['status'] == 'accepted' and not (f.accepted() and f.eligible(f.p)): errors.append('invalid_acceptance')
        if f.r['status'] == 'scheduled' and not f.appointment_valid(): errors.append('invalid_appointment')
        if f.r['status'] in {'completed','closed'}:
            if not any(a['status']=='completed' and f.booking_evidence(a,historical=True) for a in f.linked('appointments')):
                errors.append('invalid_completed_appointment')
        if f.r['status'] == 'closed' and not f.closure(): errors.append('invalid_closure')
        if f.r['status'] == 'escalated' and not f.linked('escalations'): errors.append('missing_ticket')
        return errors

    def history_violations(self):
        errors=[]
        for log in self.logs:
            before, after = log['state_before_operation'], log['state_after_operation']
            if before == after:
                continue  # Rejected attempts, including calls with external events, are diagnostic.
            pre = Facts(self.task,before,log['simulated_time_after'])
            post = Facts(self.task,after,log['simulated_time_after'])
            label = log['event_id']+':'
            if not log['ok']: errors.append(label+'failed_call_changed_state')
            if log['tool_name'] not in MUTATION_NAMES: errors.append(label+'nonmutation_changed_state')
            for field in ('patient_id','encounter_id','target_specialty','referring_clinician_id','allowed_recipient_ids','scheduling_constraints'):
                if pre.r[field] != post.r[field]: errors.append(label+'changed_intent_or_policy')
            # No agent tool may alter clinical records, payer coverage, directory,
            # report contents or slot timing. Event changes are outside this interval.
            for table in ('patients','encounters','providers','documents','reports'):
                if before[table] != after[table]: errors.append(label+'unauthorized_record_mutation:'+table)
            for ident,slot in before['slots'].items():
                updated=after['slots'].get(ident)
                if updated is None or {k:v for k,v in slot.items() if k!='available'} != {k:v for k,v in updated.items() if k!='available'}:
                    errors.append(label+'slot_record_mutation')
            if pre.r['provider_id'] != post.r['provider_id'] and not post.eligible(post.p): errors.append(label+'invalid_routing')
            for ident in set(post.r['attached_document_ids']) - set(pre.r['attached_document_ids']):
                d=after['documents'].get(ident)
                if not d or not any(post.qualifies(d,r) for r in post.p['required_document_rules']): errors.append(label+'invalid_attachment')
            if len(post.appointments()) > 1: errors.append(label+'duplicate_appointment')
            for ident,a in after['authorizations'].items():
                old=before['authorizations'].get(ident)
                if old is None:
                    denied=any(x['provider_id']==pre.r['provider_id'] and x['insurance_plan_id']==pre.patient['insurance_plan_id']
                               and x['coverage_version']==pre.patient['coverage_version'] and x['status']=='denied'
                               and x['human_appeal_required'] for x in pre.linked('authorizations'))
                    if not (log['tool_name']=='request_authorization' and pre.eligible(pre.p) and pre.packet()
                            and not denied and a['referral_id']==pre.rid and a['provider_id']==pre.r['provider_id']
                            and a['insurance_plan_id']==pre.patient['insurance_plan_id']
                            and a['coverage_version']==pre.patient['coverage_version']):
                        errors.append(label+'invalid_authorization_creation')
                elif old!=a:
                    allowed=dict(old,status='invalidated')
                    if not (log['tool_name']=='reroute_referral' and a==allowed and old['status'] in {'approved','pending'}
                            and old['provider_id']!=post.r['provider_id']):
                        errors.append(label+'authorization_record_tampering')
            for ident,a in after['acceptances'].items():
                if ident not in before['acceptances'] and not (log['tool_name']=='submit_referral'
                        and pre.eligible(pre.p) and pre.packet()
                        and (not pre.p.get('submission_requires_authorization') or pre.authorization())
                        and post.accepted(ident)):
                    errors.append(label+'invalid_acceptance_creation')
            for aid,ap in after['appointments'].items():
                old=before['appointments'].get(aid)
                if old == ap: continue
                if old is not None:
                    errors.append(label+'modified_existing_appointment')
                    continue
                slot=before['slots'].get(ap['slot_id'])
                au=before['authorizations'].get(ap.get('authorization_id'))
                if not (ap['status']=='scheduled' and slot and slot['available'] and pre.slot_ok(slot)
                        and time(slot['start_at'])>time(pre.at) and pre.accepted() and pre.eligible(pre.p)
                        and ap['acceptance_id']==pre.r['acceptance_id'] and ap['patient_id']==pre.r['patient_id']
                        and ap['referral_id']==pre.rid and ap['provider_id']==pre.r['provider_id']
                        and ap['booked_at']==log['simulated_time_after']
                        and (not pre.p['authorization_required'] or pre.valid_auth(au,visit=slot['start_at'] if pre.r.get('authorization_valid_on_visit') else None))):
                    errors.append(label+'booking_without_valid_prerequisites')
            for aid in set(before['appointments'])-set(after['appointments']): errors.append(label+'deleted_appointment')
            for did,d in after['deliveries'].items():
                if before['deliveries'].get(did)==d: continue
                report=before['reports'].get(d['report_id'])
                if not (pre.r['status']=='completed' and pre.s['encounters'][pre.r['encounter_id']]['status']=='completed'
                        and d['referral_id']==pre.rid and report and pre.report_matches(report)
                        and d['recipient_id'] in pre.r['allowed_recipient_ids'] and d['report_version']==report['version']):
                    errors.append(label+'invalid_report_delivery')
            if post.r['status']=='closed' and pre.r['status']!='closed' and not pre.closure(): errors.append(label+'receipt_free_closure')
            if post.r['status']=='accepted' and not (post.accepted() and post.eligible(post.p)): errors.append(label+'invalid_acceptance')
            for c in self.ev.get('task_constraints',[]):
                if c['name']=='provider_unchanged' and post.r['provider_id']!=c['args']['provider_id']:
                    errors.append(label+'provider_changed')
                if c['name']=='preserve_existing_appointment':
                    aid=c['args']['appointment_id']
                    if after['appointments'].get(aid)!=self.initial['appointments'][aid]: errors.append(label+'existing_appointment_changed')
        return errors

    def grade(self):
        try:
            errors=self.consistency(self.state,self.runtime['time'])
            history=self.history_violations()
            constraints=[]
            for c in self.ev.get('task_constraints',[]):
                name,args=c['name'],c['args']
                if name=='preserve_existing_appointment':
                    ok=self.state['appointments'].get(args['appointment_id'])==self.initial['appointments'][args['appointment_id']]
                elif name=='provider_unchanged': ok=self.f.r['provider_id']==args['provider_id']
                else: ok=False
                if not ok: constraints.append(name)
            fired={e['event_id'] for l in self.logs for e in l['environment_events']}
            missing_events=sorted(set(self.ev.get('required_event_ids',[]))-fired)
            outcomes=[]
            for outcome in self.ev['allowed_outcomes']:
                predicates={p['name']:p['args']=={'referral_id':self.f.rid} and self.predicate(p['name']) for p in outcome['required_predicates']}
                outcomes.append({'outcome_id':outcome['outcome_id'],'predicates':predicates,
                                 'passed':self.f.r['status']==outcome['terminal_status'] and bool(predicates) and all(predicates.values())})
            return {'task_id':self.task['task_id'],'success':any(o['passed'] for o in outcomes) and not (errors or history or constraints or missing_events),
                    'outcomes':outcomes,'final_state_errors':errors,'hard_violations':history,
                    'failed_constraints':constraints,'missing_required_events':missing_events,
                    'diagnostics':{'rejected_attempts':sum(not l['ok'] and l['state_before_operation']==l['state_after_operation'] for l in self.logs),
                                   'premature_attempts':sum(bool(l['premature']) for l in self.logs),
                                   'tool_attempts':len(self.logs)}}
        except (KeyError,TypeError,ValueError,AttributeError) as ex:
            return {'task_id':self.task.get('task_id'),'success':None,'status':'infrastructure_error','grading_error':f'{type(ex).__name__}: {ex}'}


ID_FIELDS_BY_TABLE = {'patients':'patient_id','encounters':'encounter_id','referrals':'referral_id','providers':'provider_id',
                     'documents':'document_id','authorizations':'authorization_id','acceptances':'acceptance_id','slots':'slot_id',
                     'appointments':'appointment_id','reports':'report_id','deliveries':'delivery_id','escalations':'ticket_id'}
ID_FIELDS = set(ID_FIELDS_BY_TABLE.values())
LINKS = {v:k for k,v in ID_FIELDS_BY_TABLE.items()}
LINKS['supersedes_report_id']='reports'
MUTATION_NAMES = {'attach_document','submit_referral','reroute_referral','request_authorization','schedule_appointment',
                  'reconcile_appointment','deliver_report','close_referral','escalate'}
ESCALATION_PREDICATES = {'escalation_ticket_valid','barrier_true','evidence_supports_barrier','human_action_allowed'}


def grade(task, state, logs, runtime):
    """Grade trusted exports without modifying them; fail closed on malformed data."""
    try:
        return Grader(task,state,logs,runtime).grade()
    except (KeyError,TypeError,ValueError,AttributeError,StopIteration) as ex:
        return {'task_id':task.get('task_id'),'success':None,'status':'infrastructure_error','grading_error':f'{type(ex).__name__}: {ex}'}
