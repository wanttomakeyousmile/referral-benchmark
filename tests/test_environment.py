import copy
import json
import tempfile
import unittest
from pathlib import Path
from referral_recover import Environment, TaskError, CallConflict, BudgetExceeded, StaleSession
from referral_recover.catalog import TOOLS

ROOT=Path(__file__).resolve().parents[1]
def task(n=1):return json.loads((ROOT/f'tasks/dev/DEV_{n:03d}.json').read_text())

class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.envs=[];self.start()
    def tearDown(self):
        for e in self.envs:e.close()
        self.temp.cleanup()
    def start(self,t=None,budget=100):
        env=Environment.create(t or task(),Path(self.temp.name)/f'run{len(self.envs)}.sqlite',max_tool_calls=budget)
        self.envs.append(env);self.e=env;self.s=env.session();return env
    def call(self,name,**kw):return self.s.call(name,kw)
    def ok(self,name,**kw):
        r=self.call(name,**kw);self.assertTrue(r['ok'],r);return r['data']
    def error(self,name,code,**kw):
        r=self.call(name,**kw);self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],code);return r
    def ready(self):
        self.ok('attach_document',referral_id='R1',document_id='ECHO1')
        self.ok('submit_referral',referral_id='R1')
    def book(self):self.ready();return self.ok('schedule_appointment',referral_id='R1',slot_id='SLOT_A')['record']

    def test_document_repair(self):
        self.assertEqual(self.ok('get_referral',referral_id='R1')['status'],'rejected')
        before=self.e.snapshot()
        self.error('submit_referral','PACKET_INCOMPLETE',referral_id='R1')
        self.assertEqual(before,self.e.snapshot())
        self.ready()
        r=self.ok('get_referral',referral_id='R1')
        self.assertEqual(r['status'],'accepted');self.assertTrue(r['acceptance_valid'])
        self.assertTrue(self.e.logs()[1]['premature'])
    def test_idempotent_new_calls(self):
        self.ready();before=self.e.snapshot()
        self.assertFalse(self.ok('attach_document',referral_id='R1',document_id='ECHO1')['changed'])
        self.assertFalse(self.ok('submit_referral',referral_id='R1')['changed'])
        self.assertEqual(before,self.e.snapshot())
    def test_unknown_malformed_and_scope(self):
        self.error('delete_all','UNKNOWN_TOOL')
        self.error('get_referral','INVALID_ARGUMENTS',referral_id='R1',extra='x')
        self.error('get_referral','RECORD_OUT_OF_SCOPE',referral_id='R_OTHER')
        self.error('get_referral','INVALID_ARGUMENTS',referral_id=1)
        self.assertEqual(self.e.runtime_info()['tool_attempts'],4)
    def test_unavailable_document(self):
        self.start(task(4));before=self.e.snapshot()
        self.error('attach_document','DOCUMENT_UNAVAILABLE',referral_id='R1',document_id='ECHO1')
        self.assertEqual(before,self.e.snapshot())
    def test_wrong_encounter_document(self):
        t=task();s=t['environment']['initial_state'];s['encounters'].append({'encounter_id':'E2','patient_id':'P1','status':'completed'})
        s['documents'][1]['encounter_id']='E2';self.start(t)
        self.error('attach_document','DOCUMENT_MISMATCH',referral_id='R1',document_id='ECHO1')
    def test_rerouting_and_auth_invalidation(self):
        self.start(task(2));self.ready()
        self.assertEqual(self.e.snapshot()['referrals']['R1']['status'],'rejected')
        self.assertEqual(self.e.runtime_info()['fired'],['INTAKE_CLOSES'])
        self.ok('reroute_referral',referral_id='R1',provider_id='CARD_B')
        self.assertEqual(self.e.snapshot()['authorizations']['AUTH1']['status'],'invalidated')
        self.ok('submit_referral',referral_id='R1')
        self.error('schedule_appointment','AUTHORIZATION_INVALID',referral_id='R1',slot_id='SLOT_B')
        self.ok('request_authorization',referral_id='R1')
        self.ok('schedule_appointment',referral_id='R1',slot_id='SLOT_B')
        self.assertEqual(self.e.snapshot()['referrals']['R1']['status'],'scheduled')
    def test_intake_event_does_not_fire_for_incomplete_packet(self):
        self.start(task(2));self.error('submit_referral','PACKET_INCOMPLETE',referral_id='R1')
        self.assertEqual(self.e.runtime_info()['fired'],[])
    def test_auth_denial_is_domain_outcome(self):
        t=task();t['environment']['initial_state']['authorizations']=[]
        t['environment']['simulation']['authorization_decisions']={'CARD_A':'denied'};self.start(t);self.ready()
        record=self.ok('request_authorization',referral_id='R1')['record'];self.assertEqual(record['status'],'denied')
        self.error('request_authorization','HUMAN_APPEAL_REQUIRED',referral_id='R1')
        self.error('schedule_appointment','AUTHORIZATION_INVALID',referral_id='R1',slot_id='SLOT_A')
    def test_pending_auth_never_satisfies_booking(self):
        t=task();t['environment']['initial_state']['authorizations']=[]
        t['environment']['simulation']['authorization_decisions']={'CARD_A':'pending'}
        t['public_policy']['pending_requires_human']=True;self.start(t);self.ready()
        self.assertEqual(self.ok('request_authorization',referral_id='R1')['record']['status'],'pending')
        self.assertFalse(self.ok('request_authorization',referral_id='R1')['changed'])
        self.error('schedule_appointment','AUTHORIZATION_INVALID',referral_id='R1',slot_id='SLOT_A')
    def test_authorization_expiration(self):
        t=task();t['environment']['initial_state']['authorizations'][0]['valid_until']='2026-09-01T09:03:00Z'
        self.start(t);self.ready()
        self.error('schedule_appointment','AUTHORIZATION_INVALID',referral_id='R1',slot_id='SLOT_A')
        self.assertEqual(self.e.snapshot()['authorizations']['AUTH1']['status'],'expired')
    def test_slot_constraints_and_duplicate(self):
        t=task();t['environment']['initial_state']['referrals'][0]['scheduling_constraints']={'latest':'2026-09-03T00:00:00Z'}
        self.start(t);self.ready();self.error('schedule_appointment','SLOT_CONSTRAINT_VIOLATION',referral_id='R1',slot_id='SLOT_A')
        self.start();self.book();self.error('schedule_appointment','DUPLICATE_APPOINTMENT',referral_id='R1',slot_id='SLOT_A')
    def test_slot_disappears_before_booking(self):
        t=task();t['environment']['events']=[{'event_id':'SLOT_LOST','trigger':{'phase':'before','tool':'schedule_appointment'},
             'changes':[{'collection':'slots','id':'SLOT_A','set':{'available':False}}]}]
        self.start(t);self.ready();self.error('schedule_appointment','SLOT_UNAVAILABLE',referral_id='R1',slot_id='SLOT_A')
        log=self.e.logs()[-1];self.assertFalse(log['operation_changed']);self.assertEqual(len(log['environment_events']),1)
    def test_coverage_event_invalidates_authorization(self):
        t=task();t['environment']['events']=[{'event_id':'COVERAGE','trigger':{'phase':'time','at':'2026-09-01T09:03:00Z'},
            'changes':[{'collection':'patients','id':'P1','set':{'coverage_version':2}}]}]
        self.start(t);self.ready();self.error('schedule_appointment','AUTHORIZATION_INVALID',referral_id='R1',slot_id='SLOT_A')
    def test_completed_report_workflow(self):
        self.start(task(3));self.error('close_referral','CLOSURE_REQUIREMENTS_UNMET',referral_id='R1')
        self.error('deliver_report','REPORT_MISMATCH',referral_id='R1',report_id='REPORT_OLD',recipient_id='PCP1')
        self.error('deliver_report','RECIPIENT_NOT_ALLOWED',referral_id='R1',report_id='REPORT_GOOD',recipient_id='STRANGER')
        d=self.ok('deliver_report',referral_id='R1',report_id='REPORT_GOOD',recipient_id='PCP1')['record']
        self.assertIsNotNone(self.ok('get_report_delivery',referral_id='R1',delivery_id=d['delivery_id'])['receipt_id'])
        self.assertFalse(self.ok('deliver_report',referral_id='R1',report_id='REPORT_GOOD',recipient_id='PCP1')['changed'])
        self.ok('close_referral',referral_id='R1');self.assertFalse(self.ok('close_referral',referral_id='R1')['changed'])
        self.error('attach_document','INVALID_REFERRAL_STATE',referral_id='R1',document_id='ECHO1')
    def test_failed_delivery_does_not_allow_closure(self):
        t=task(3);t['environment']['simulation']['delivery_outcomes']={'PCP1':'failed'};self.start(t)
        d=self.ok('deliver_report',referral_id='R1',report_id='REPORT_GOOD',recipient_id='PCP1')['record']
        self.assertEqual(d['status'],'failed');self.assertIsNone(d['receipt_id'])
        self.error('close_referral','CLOSURE_REQUIREMENTS_UNMET',referral_id='R1')
    def test_report_withdrawal_invalidates_receipt_for_closure(self):
        t=task(3);t['environment']['events']=[{'event_id':'WITHDRAW','trigger':{'phase':'before','tool':'close_referral'},
            'changes':[{'collection':'reports','id':'REPORT_GOOD','set':{'status':'withdrawn'}}]}]
        self.start(t);self.ok('deliver_report',referral_id='R1',report_id='REPORT_GOOD',recipient_id='PCP1')
        self.error('close_referral','CLOSURE_REQUIREMENTS_UNMET',referral_id='R1')
    def test_escalation_records_without_answer_oracle(self):
        ev=self.call('get_documents',referral_id='R1')['observation_event_id']
        args=dict(referral_id='R1',blocker_code='required_document_unavailable',evidence_event_ids=[ev],attempted_action_event_ids=[],
                  reason_unable_to_proceed='Claim of unavailable document',human_action_code='obtain_required_document',required_human_action='Obtain report')
        # Deliberately unjustified: tool records it; the future grader must fail it.
        self.assertEqual(self.ok('escalate',**args)['record']['blocker_code'],'required_document_unavailable')
        self.assertEqual(self.e.snapshot()['referrals']['R1']['status'],'escalated')
    def test_escalation_rejects_fabricated_evidence(self):
        self.error('escalate','INVALID_EVIDENCE_REFERENCE',referral_id='R1',blocker_code='required_document_unavailable',
            evidence_event_ids=['FAKE'],attempted_action_event_ids=[],reason_unable_to_proceed='Missing report',human_action_code='obtain_required_document',required_human_action='Obtain report')
    def test_retry_and_conflict(self):
        a={'referral_id':'R1','document_id':'ECHO1'}
        first=self.s.call('attach_document',a,call_id='same');info=self.e.runtime_info();logs=self.e.logs()
        self.assertEqual(first,self.s.call('attach_document',a,call_id='same'))
        self.assertEqual(info,self.e.runtime_info());self.assertEqual(logs,self.e.logs())
        with self.assertRaises(CallConflict):self.s.call('submit_referral',{'referral_id':'R1'},call_id='same')
    def test_budget_and_cached_retry_at_cap(self):
        self.start(budget=1);first=self.s.call('get_referral',{'referral_id':'R1'},call_id='once')
        self.assertEqual(first,self.s.call('get_referral',{'referral_id':'R1'},call_id='once'))
        with self.assertRaises(BudgetExceeded):self.call('get_documents',referral_id='R1')
    def test_reset_clears_state_events_cache_and_memory(self):
        self.start(task(2));initial=self.e.snapshot();old=self.s;old.memory['plan']='stale';self.ready()
        old_run=self.e.runtime_info()['run_id'];self.s=self.e.reset()
        self.assertNotEqual(old_run,self.e.runtime_info()['run_id']);self.assertEqual(self.e.snapshot(),initial)
        self.assertEqual(self.e.logs(),[]);self.assertEqual(self.e.runtime_info()['fired'],[])
        self.assertEqual(self.e.runtime_info()['counter'],0);self.assertEqual(self.e.runtime_info()['tool_attempts'],0)
        with self.assertRaises(StaleSession):old.call('get_referral',{'referral_id':'R1'})
        self.assertEqual(old.memory,{});self.assertEqual(self.s.memory,{})
        self.ready();self.assertEqual(self.e.runtime_info()['fired'],['INTAKE_CLOSES'])
    def test_independent_databases(self):
        first=self.e;self.ready();saved=first.snapshot();self.start();self.e.reset()
        self.assertEqual(first.snapshot(),saved)
        self.assertNotEqual(first.snapshot(),self.e.snapshot())
    def test_no_overwrite(self):
        with self.assertRaises(FileExistsError):Environment.create(task(),self.e.path)
    def test_visibility(self):
        context=json.dumps(self.s.context())
        for secret in ('simulation','initial_blocker_codes','evaluation','initial_state','reference_trajectories','events'):
            self.assertNotIn(secret,context)
        self.assertEqual({x['name'] for x in self.s.definitions()},set(TOOLS))
    def test_bad_task_reset_is_atomic(self):
        self.ready();before=self.e.snapshot();logs=self.e.logs();bad=task();bad['environment']['initial_state']['documents'][1]['document_id']='ORDER1'
        with self.assertRaises(TaskError):self.e.reset(bad)
        self.assertEqual(before,self.e.snapshot());self.assertEqual(logs,self.e.logs())
    def test_reopen_persists_cache(self):
        r=self.s.call('get_referral',{'referral_id':'R1'},call_id='persisted')
        with Environment(self.e.path) as reopened:
            self.assertEqual(r,reopened.session().call('get_referral',{'referral_id':'R1'},call_id='persisted'))
    def test_historical_reconciliation(self):
        ap=self.book();snap=self.e.snapshot();t=task()
        t['environment']['initial_state']={k:list(v.values()) for k,v in snap.items()}
        t['environment']['initial_state']['referrals'][0]['status']='accepted'
        t['environment']['clock_start']='2026-09-01T10:00:00Z';self.start(t)
        self.ok('reconcile_appointment',referral_id='R1',appointment_id=ap['appointment_id'])
        self.assertEqual(len(self.e.snapshot()['appointments']),1)
    def test_all_read_tools(self):
        for name,args in [
            ('get_coverage',{'referral_id':'R1'}),('get_documents',{'referral_id':'R1'}),
            ('get_provider_requirements',{'provider_id':'CARD_A'}),('find_providers',{'referral_id':'R1'}),
            ('check_provider_eligibility',{'referral_id':'R1','provider_id':'CARD_A'}),
            ('check_authorization',{'referral_id':'R1'}),('find_appointment_slots',{'referral_id':'R1','provider_id':'CARD_A'}),
            ('get_appointments',{'referral_id':'R1'}),('get_consultation_reports',{'referral_id':'R1'})]:
            self.ok(name,**args)
    def test_after_event_observation_is_current(self):
        t=task();t['environment']['events']=[{'event_id':'CHANGE','trigger':{'phase':'after','tool':'get_coverage'},
            'changes':[{'collection':'patients','id':'P1','set':{'coverage_version':2}}]}]
        self.start(t);self.assertEqual(self.ok('get_coverage',referral_id='R1')['authoritative']['coverage_version'],2)
    def test_submission_auth_policy(self):
        t=task();t['environment']['initial_state']['providers'][0]['submission_requires_authorization']=True
        t['environment']['initial_state']['authorizations']=[];self.start(t)
        self.ok('attach_document',referral_id='R1',document_id='ECHO1')
        self.error('submit_referral','AUTHORIZATION_INVALID',referral_id='R1')


    def test_guarded_event_bad_scope_is_tool_error(self):
        t=task(2);t['environment']['events'][0]['trigger'].pop('arguments_match')
        self.start(t)
        self.error('submit_referral','RECORD_OUT_OF_SCOPE',referral_id='NOT_A_REFERRAL')
        self.assertEqual(self.e.runtime_info()['fired'],[])
    def test_reconciliation_rejects_stale_coverage(self):
        self.book();t=task();t['environment']['initial_state']={k:list(v.values()) for k,v in self.e.snapshot().items()}
        t['environment']['clock_start']='2026-09-01T10:00:00Z'
        t['environment']['initial_state']['patients'][0]['coverage_version']=2
        self.start(t)
        aid=next(iter(self.e.snapshot()['appointments']))
        self.error('reconcile_appointment','APPOINTMENT_INVALID',referral_id='R1',appointment_id=aid)
    def test_wrong_patient_document(self):
        t=task();st=t['environment']['initial_state']
        st['patients'].append({'patient_id':'P2','insurance_plan_id':'PLAN_A','coverage_version':1})
        st['documents'][1]['patient_id']='P2';self.start(t)
        self.error('attach_document','DOCUMENT_MISMATCH',referral_id='R1',document_id='ECHO1')
    def test_ineligible_reroute_is_atomic(self):
        t=task();t['environment']['initial_state']['providers'][1]['accepting_referrals']=False
        self.start(t);before=self.e.snapshot()
        self.error('reroute_referral','PROVIDER_INELIGIBLE',referral_id='R1',provider_id='CARD_B')
        self.assertEqual(before,self.e.snapshot())
    def test_visit_date_authorization(self):
        t=task();t['environment']['initial_state']['referrals'][0]['authorization_valid_on_visit']=True
        t['environment']['initial_state']['authorizations'][0]['valid_until']='2026-09-05T00:00:00Z'
        self.start(t);self.ready();self.error('schedule_appointment','AUTHORIZATION_INVALID',referral_id='R1',slot_id='SLOT_A')
    def test_unexpected_engine_failure_rolls_back_transaction(self):
        from unittest.mock import patch
        from referral_recover.environment import Engine
        state=self.e.snapshot();info=self.e.runtime_info()
        with patch.object(Engine,'execute',side_effect=RuntimeError('simulated crash')):
            with self.assertRaises(RuntimeError):self.call('get_referral',referral_id='R1')
        self.assertEqual(state,self.e.snapshot());self.assertEqual(info,self.e.runtime_info());self.assertEqual(self.e.logs(),[])
    def test_reset_allows_call_id_reuse_without_old_cache(self):
        before=self.s.call('get_referral',{'referral_id':'R1'},call_id='x')
        self.ready();self.s=self.e.reset()
        after=self.s.call('get_referral',{'referral_id':'R1'},call_id='x')
        self.assertEqual(before,after);self.assertEqual(len(self.e.logs()),1)
    def test_bad_event_is_rejected_before_create(self):
        t=task();t['environment']['events']=[{'event_id':'BAD','trigger':{'phase':'before','tool':'get_referral'},
            'changes':[{'collection':'referrals','id':'R1','set':{'patient_id':'P2'}}]}]
        with self.assertRaises(TaskError):self.start(t)

if __name__=='__main__':unittest.main()
