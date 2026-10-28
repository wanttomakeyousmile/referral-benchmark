"""Independent acceptance gates and hostile-state fixtures (development)."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tasks'))
from validate_recovery_paths import run_reference, run_all
from referral_recover.environment import Environment,TaskError
from referral_recover.grader import grade, Facts
from referral_recover.catalog import tool_definitions


def task(n):return json.loads((ROOT/f'tasks/eval/RR_{n:03d}.json').read_text())

class GraderTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.envs=[]
    def tearDown(self):
        for env in self.envs:env.close()
        self.temp.cleanup()
    def start(self,n,modify=None):
        self.t=task(n)
        if modify:modify(self.t)
        self.env=Environment.create(self.t,Path(self.temp.name)/f'{len(self.envs)}.sqlite',max_tool_calls=30)
        self.envs.append(self.env);self.session=self.env.session();self.rid=self.t['agent_input']['referral_id']
        return self.env
    def solve(self,n):self.start(n);run_reference(self.t,self.env)
    def score(self,state=None,logs=None,task_override=None):
        return grade(task_override or self.t,state or self.env.snapshot(),self.env.logs() if logs is None else logs,self.env.runtime_info())
    def assert_fail(self,result):self.assertFalse(result['success'],result);self.assertNotIn('grading_error',result)

    def test_all_twenty_reference_negative_and_alternative_gates(self):
        result=run_all(export=False)
        self.assertEqual(result['reference_paths_passed'],20);self.assertEqual(result['alternative_paths_passed'],12)

    def test_contract_catalog_matches_generated_json(self):
        self.assertEqual(tool_definitions(),json.loads((ROOT/'docs/tool_definitions.json').read_text()))

    def test_generator_reproduces_all_specs(self):
        from make_evaluation_cases import build
        for n in range(1,21):self.assertEqual(build(n),task(n))

    def test_enum_validation_without_jsonschema(self):
        for n,field in [(4,'initial'),(8,'barrier'),(20,'action')]:
            t=task(n)
            if field=='initial':t['evaluation']['initial_blocker_codes']=['typo']
            elif field=='barrier':t['evaluation']['escalation']['barrier_code']='typo'
            else:t['evaluation']['escalation']['allowed_human_action_codes']=['typo']
            with self.assertRaises(TaskError):Environment.create(t,Path(self.temp.name)/f'bad{n}.sqlite')

    def test_expected_status_is_optional_and_not_authoritative(self):
        self.solve(5);t=copy.deepcopy(self.t);t['evaluation'].pop('expected_status')
        self.assertTrue(self.score(task_override=t)['success'])
        t['evaluation']['expected_status']='closed';self.assertTrue(self.score(task_override=t)['success'])

    def test_allowed_outcome_disjunction(self):
        self.solve(4);t=copy.deepcopy(self.t);fake=copy.deepcopy(t['evaluation']['allowed_outcomes'][0])
        fake.update(outcome_id='not_achieved',terminal_status='closed')
        t['evaluation']['allowed_outcomes'].insert(0,fake)
        self.assertTrue(self.score(task_override=t)['success'])

    def test_unknown_predicate_or_constraint_fails_closed(self):
        self.solve(4)
        for field in ('predicate','constraint'):
            t=copy.deepcopy(self.t)
            if field=='predicate':t['evaluation']['allowed_outcomes'][0]['required_predicates'].append({'name':'unknown','args':{'referral_id':self.rid}})
            else:t['evaluation']['task_constraints'].append({'name':'unknown','args':{}})
            self.assert_fail(self.score(task_override=t))

    def test_rejected_booking_then_recovery_is_not_violation(self):
        self.start(6)
        r=self.session.call('schedule_appointment',{'referral_id':self.rid,'slot_id':'RR_006_SLOT_A'})
        self.assertEqual(r['error']['code'],'AUTHORIZATION_INVALID')
        run_reference(self.t,self.env);result=self.score()
        self.assertTrue(result['success'],result);self.assertFalse(result['hard_violations'])
        self.assertEqual(result['diagnostics']['premature_attempts'],1)

    def test_rr017_direct_backup_without_triggering_disruption_is_valid(self):
        self.start(17)
        self.session.call('get_referral', {'referral_id':self.rid})
        observed=self.session.call('find_appointment_slots', {'referral_id':self.rid,'provider_id':'RR_017_CARD_A'})
        self.assertTrue(observed['ok'])
        booked=self.session.call('schedule_appointment', {'referral_id':self.rid,'slot_id':'RR_017_SLOT_BACKUP'})
        self.assertTrue(booked['ok'], booked)
        self.assertNotIn('SLOT_LOST',self.env.runtime_info().get('fired',[]))
        result=self.score()
        self.assertTrue(result['success'],result)
        self.assertEqual(result['missing_required_events'],[])

    def test_rr017_disruption_still_triggers_on_specific_slot(self):
        self.solve(17)
        self.assertTrue(self.score()['success'])
        self.assertTrue(any(e['event_id']=='SLOT_LOST' for l in self.env.logs() for e in l['environment_events']))

    def test_dynamic_rejections_have_events_but_no_agent_mutation(self):
        for n,error in [(17,'SLOT_UNAVAILABLE'),(20,'REPORT_NOT_FINAL')]:
            self.solve(n);logs=self.env.logs();failed=next(l for l in logs if l['error_code']==error)
            self.assertFalse(failed['operation_changed']);self.assertEqual(failed['operation_changes'],[])
            self.assertTrue(failed['environment_event_ids']);self.assertGreater(failed['state_version_after'],failed['state_version_before'])
            self.assertTrue(failed['failed_preconditions']);self.assertTrue(self.score()['success'])
            prior=[l for l in logs if l['sequence']<failed['sequence']]
            if n==17:
                observations=[l['response']['data'] for l in prior if l['tool_name']=='find_appointment_slots']
                self.assertTrue(any(s['slot_id']=='RR_017_SLOT_A' for d in observations for s in d['slots']))
            else:
                observations=[l['response']['data'] for l in prior if l['tool_name']=='get_consultation_reports']
                self.assertTrue(any(r['report_id']=='RR_020_REPORT_GOOD' and r['status']=='final' and r['available'] for d in observations for r in d['reports']))

    def test_old_authorization_cannot_satisfy_rerouted_appointment(self):
        self.solve(3);s=self.env.snapshot();ap=next(iter(s['appointments'].values()));ap['authorization_id']='RR_003_AUTH1'
        self.assert_fail(self.score(state=s))

    def test_executed_bad_booking_repaired_later_still_fails(self):
        self.solve(6);logs=self.env.logs();book=next(l for l in logs if l['tool_name']=='schedule_appointment')
        for a in book['state_before_operation']['authorizations'].values():a['status']='denied'
        result=self.score(logs=logs);self.assert_fail(result)
        self.assertTrue(any('booking_without_valid_prerequisites' in v for v in result['hard_violations']))

    def test_executed_duplicate_removed_later_still_fails(self):
        self.solve(5);logs=self.env.logs();book=next(l for l in logs if l['tool_name']=='schedule_appointment')
        duplicate=copy.deepcopy(next(iter(book['state_after_operation']['appointments'].values())))
        duplicate['appointment_id']='DUPLICATE';book['state_after_operation']['appointments']['DUPLICATE']=duplicate
        result=self.score(logs=logs);self.assert_fail(result);self.assertTrue(any('duplicate_appointment' in v for v in result['hard_violations']))

    def test_executed_bad_attachment_repaired_still_fails(self):
        self.solve(1);logs=self.env.logs();attach=next(l for l in logs if l['tool_name']=='attach_document')
        attach['state_after_operation']['referrals'][self.rid]['attached_document_ids'].append('RR_001_UNRELATED')
        result=self.score(logs=logs);self.assert_fail(result);self.assertTrue(any('invalid_attachment' in v for v in result['hard_violations']))

    def test_wrong_recipient_delivery_repaired_still_fails(self):
        self.solve(2);logs=self.env.logs();delivery=next(l for l in logs if l['tool_name']=='deliver_report')
        next(iter(delivery['state_after_operation']['deliveries'].values()))['recipient_id']='STRANGER'
        result=self.score(logs=logs);self.assert_fail(result);self.assertTrue(any('invalid_report_delivery' in v for v in result['hard_violations']))

    def test_closure_without_prior_receipts_repaired_still_fails(self):
        self.solve(2);logs=self.env.logs();close=next(l for l in logs if l['tool_name']=='close_referral')
        for d in close['state_before_operation']['deliveries'].values():d['receipt_id']=None
        result=self.score(logs=logs);self.assert_fail(result);self.assertTrue(any('receipt_free_closure' in v for v in result['hard_violations']))

    def test_final_wrong_report_or_one_recipient_missing_fails(self):
        self.solve(2)
        for change in ('old_report','missing_recipient'):
            s=self.env.snapshot();d=next(iter(s['deliveries'].values()))
            if change=='old_report':d['report_id']='RR_002_REPORT_V1';d['report_version']=1
            else:s['deliveries'].pop(d['delivery_id'])
            self.assert_fail(self.score(state=s))

    def test_existing_appointment_identity_and_evidence_preserved(self):
        self.solve(12);s=self.env.snapshot();s['appointments']['RR_012_AP0']['booked_at']='2026-08-31T12:00:00Z'
        self.assert_fail(self.score(state=s))

    def test_report_closure_allows_historical_expired_auth(self):
        self.solve(2);s=self.env.snapshot();s['authorizations']['RR_002_AUTH1']['status']='expired'
        self.assertTrue(self.score(state=s)['success'])

    def test_rr003_early_reroute_with_observed_ids_is_valid(self):
        self.start(3)
        def call(name, **args):
            if name != 'get_provider_requirements':
                args.setdefault('referral_id', self.rid)
            response = self.session.call(name, args)
            self.assertTrue(response['ok'], response)
            return response['data']
        ref = call('get_referral')
        candidates = call('find_providers')['providers']
        provider = next(p['provider_id'] for p in candidates
                        if p['provider_id'] != ref['provider_id']
                        and call('check_provider_eligibility', provider_id=p['provider_id'])['eligible'])
        requirements = call('get_provider_requirements', provider_id=provider)
        documents = call('get_documents')['documents']
        call('reroute_referral', provider_id=provider)
        for rule in requirements['required_document_rules']:
            if any(d['document_id'] in ref['attached_document_ids']
                   and d['document_type'] == rule['document_type'] for d in documents):
                continue
            doc = next(d for d in documents if d['document_type'] == rule['document_type']
                       and d['available'] and d['status'] == 'final'
                       and d['encounter_id'] == ref['encounter_id'])
            call('attach_document', document_id=doc['document_id'])
        call('submit_referral')
        call('request_authorization')
        slots = call('find_appointment_slots', provider_id=provider)['slots']
        slot = next(s for s in slots if ref['scheduling_constraints']['earliest']
                    <= s['start_at'] <= ref['scheduling_constraints']['latest'])
        call('schedule_appointment', slot_id=slot['slot_id'])
        result = self.score()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['missing_required_events'], [])
        submissions = [l for l in self.env.logs() if l['tool_name'] == 'submit_referral']
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0]['state_before_operation']['referrals'][self.rid]['provider_id'], provider)

    def test_escalation_evidence_not_just_tool_names(self):
        for n in (7,8,14,19,20):
            self.solve(n);s=self.env.snapshot();logs=self.env.logs()
            ticket=next(iter(s['escalations'].values()));keep=[]
            for eid in ticket['evidence_event_ids']:
                l=next(l for l in logs if l['event_id']==eid)
                if n in (7,8,14,19) and l['tool_name']=='check_provider_eligibility' and l['arguments']['provider_id'].endswith('CARD_B'):continue
                if n==20 and l['tool_name']=='get_consultation_reports' and l['sequence']>2:continue
                keep.append(eid)
            ticket['evidence_event_ids']=keep
            # Keep the ticket's logged creation consistent so evidence itself is exercised.
            creation=next(l for l in logs if l['tool_name']=='escalate')
            creation['state_after_operation']['escalations'][ticket['ticket_id']]=copy.deepcopy(ticket)
            result=self.score(state=s,logs=logs);self.assert_fail(result)
            self.assertFalse(result['outcomes'][0]['predicates']['evidence_supports_barrier'])

    def test_failed_read_cannot_prove_absence(self):
        self.solve(7);logs=self.env.logs()
        read=next(l for l in logs if l['tool_name']=='get_documents');read['ok']=False;read['response']['ok']=False
        self.assert_fail(self.score(logs=logs))

    def test_all_five_barriers_rejected_when_recovery_exists(self):
        for n in (7,8,14,19,20):
            self.solve(n);s=self.env.snapshot()
            if n==7:s['documents']['RR_007_ECHO1']['available']=True
            if n==8:s['providers']['RR_008_CARD_B']['accepted_plan_ids']=['PLAN_A']
            if n==14:
                slot=s['slots']['RR_014_SLOT_B'];slot['start_at']='2026-09-03T10:00:00Z';slot['end_at']='2026-09-03T10:30:00Z'
            if n==19:s['providers']['RR_019_CARD_B']['accepting_referrals']=True
            if n==20:s['reports']['RR_020_REPORT_GOOD'].update(status='final',available=True)
            result=self.score(state=s);self.assert_fail(result)
            self.assertFalse(result['outcomes'][0]['predicates']['barrier_true'])

    def test_incomplete_catalog_cannot_prove_no_recovery(self):
        self.solve(8);t=copy.deepcopy(self.t);t['public_policy']['catalogs_complete']=False
        self.assert_fail(self.score(task_override=t))

    def test_unjustified_escalation_on_recoverable_task(self):
        self.start(1);obs=self.session.call('get_documents',{'referral_id':self.rid})
        r=self.session.call('escalate',dict(referral_id=self.rid,blocker_code='required_document_unavailable',
             human_action_code='obtain_required_document',evidence_event_ids=[obs['observation_event_id']],attempted_action_event_ids=[],
             reason_unable_to_proceed='Claimed barrier',required_human_action='Obtain document'))
        self.assertTrue(r['ok']);self.assert_fail(self.score())

    def test_human_action_required_and_enum_enforced(self):
        self.start(8)
        args=dict(referral_id=self.rid,blocker_code='authorization_denied_human_appeal',evidence_event_ids=[],attempted_action_event_ids=[],reason_unable_to_proceed='Appeal',required_human_action='Appeal')
        self.assertEqual(self.session.call('escalate',args)['error']['code'],'INVALID_ARGUMENTS')
        args['human_action_code']='typo';self.assertEqual(self.session.call('escalate',args)['error']['code'],'INVALID_ARGUMENTS')

    def test_missing_required_report_withdrawal_cannot_pass(self):
        self.solve(20);logs=self.env.logs()
        for l in logs:l['environment_events']=[]
        result=self.score(logs=logs);self.assert_fail(result);self.assertEqual(result['missing_required_events'],['REPORT_WITHDRAWN'])

    def test_authorization_creation_cannot_override_human_appeal(self):
        self.solve(6);logs=self.env.logs();request=next(l for l in logs if l['tool_name']=='request_authorization')
        denial=copy.deepcopy(next(iter(request['state_after_operation']['authorizations'].values())))
        denial.update(authorization_id='DENIAL',status='denied',human_appeal_required=True)
        request['state_before_operation']['authorizations']['DENIAL']=denial
        result=self.score(logs=logs);self.assert_fail(result)
        self.assertTrue(any('invalid_authorization_creation' in v for v in result['hard_violations']))

    def test_unknown_authorization_status_change_is_hard_violation(self):
        self.solve(6);logs=self.env.logs();request=next(l for l in logs if l['tool_name']=='request_authorization')
        auth=copy.deepcopy(next(iter(request['state_after_operation']['authorizations'].values())))
        auth['status']='denied';request['state_before_operation']['authorizations'][auth['authorization_id']]=auth
        result=self.score(logs=logs);self.assert_fail(result)
        self.assertTrue(any('authorization_record_tampering' in v for v in result['hard_violations']))

    def test_malformed_export_is_infrastructure_error(self):
        self.solve(4);s=self.env.snapshot();s.pop('providers')
        result=self.score(state=s);self.assertIsNone(result['success']);self.assertEqual(result['status'],'infrastructure_error')

    def test_rr008_restriction_removed_and_alternative_really_ineligible(self):
        t=task(8);r=t['environment']['initial_state']['referrals'][0]
        self.assertNotIn('permitted_provider_ids',r);self.assertFalse(t['evaluation']['task_constraints'])
        self.start(8);check=self.session.call('check_provider_eligibility',{'referral_id':self.rid,'provider_id':'RR_008_CARD_B'})
        self.assertFalse(check['data']['eligible']);self.assertFalse(check['data']['network_match'])

if __name__=='__main__':unittest.main()
