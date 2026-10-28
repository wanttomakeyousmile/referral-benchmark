import json,tempfile,unittest,sys,copy
from pathlib import Path
from referral_recover import Environment
from referral_recover.grader import grade
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tasks'))
from validate_recovery_paths import run_reference

class EventRecoveryTests(unittest.TestCase):
    def run_path(self,n,search_first=False,stop=False,reopen=False,invalid_first=False):
        t=json.loads((ROOT/f'tasks/eval/RR_{n:03d}.json').read_text())
        self.assertNotIn('required_event_ids',t['evaluation'])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'run.sqlite';env=Environment.create(t,path);s=env.session();rid=t['agent_input']['referral_id']
            def call(name,**args):return s.call(name,{'referral_id':rid,**args})
            ref=call('get_referral')['data']
            if invalid_first:
                response=s.call('schedule_appointment',{'referral_id':rid})
                self.assertFalse(response['ok']);self.assertEqual(env.runtime_info()['fired'],[])
            if search_first:
                slots=call('find_appointment_slots',provider_id=ref['provider_id'])['data']['slots'];slot=slots[0]['slot_id']
            else:slot=f'RR_{n:03d}_SLOT_A'
            response=call('schedule_appointment',slot_id=slot)
            self.assertFalse(response['ok']);self.assertEqual(response['error']['code'],'AUTHORIZATION_INVALID')
            self.assertEqual(env.snapshot()['appointments'],{})
            self.assertEqual(len(env.runtime_info()['fired']),1)
            if reopen:env.close();env=Environment(path);s=env.session()
            if not stop:
                self.assertTrue(call('check_authorization')['ok'])
                self.assertTrue(call('request_authorization')['ok'])
                if not search_first:call('find_appointment_slots',provider_id=ref['provider_id'])
                self.assertTrue(call('schedule_appointment',slot_id=slot)['ok'])
            score=grade(t,env.snapshot(),env.logs(),env.runtime_info())
            self.assertEqual(score['success'],not stop,score)
            self.assertEqual(score['missing_required_events'],[])
            events=[e for l in env.logs() for e in l['environment_events']]
            self.assertEqual(len(events),1)
            env.close()
    def test_search_then_attempt_repair_retry(self):
        for n in (16,18):
            with self.subTest(n=n):self.run_path(n,search_first=True)
    def test_direct_attempt_repair_search_retry(self):
        for n in (16,18):
            with self.subTest(n=n):self.run_path(n)
    def test_stop_after_rejection_fails(self):
        for n in (16,18):
            with self.subTest(n=n):self.run_path(n,stop=True)
    def test_once_only_survives_reopen(self):
        for n in (16,18):
            with self.subTest(n=n):self.run_path(n,reopen=True)
    def test_malformed_request_does_not_trigger_event(self):
        for n in (16,18):
            with self.subTest(n=n):self.run_path(n,invalid_first=True)
    def test_other_reference_outcomes_do_not_depend_on_standalone_gate(self):
        for n in (3,19,20):
            t=json.loads((ROOT/f'tasks/eval/RR_{n:03d}.json').read_text())
            with tempfile.TemporaryDirectory() as d:
                with Environment.create(t,Path(d)/'run.sqlite') as env:
                    run_reference(t,env)
                    baseline=grade(t,env.snapshot(),env.logs(),env.runtime_info())
                    no_gate=copy.deepcopy(t);no_gate['evaluation'].pop('required_event_ids',None)
                    altered=grade(no_gate,env.snapshot(),env.logs(),env.runtime_info())
                    self.assertTrue(baseline['success']);self.assertTrue(altered['success'])
                    if n in (19,20):
                        # Removing event IDs also changes evidence freshness threshold:
                        # therefore it is not a pure removal of an output success gate.
                        self.assertTrue(t['evaluation']['escalation']['require_observations_after_barrier_event'])
