"""Public contract alignment and actual handoff-call evidence regression tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tasks'))
from validate_recovery_paths import run_reference
from make_evaluation_cases import build
from referral_recover import Environment
from referral_recover.grader import grade

class PublicEscalationContractTests(unittest.TestCase):
    def task(self, n):
        return json.loads((ROOT / f'tasks/eval/RR_{n:03d}.json').read_text())

    def test_shared_public_contract_matches_grading_and_generator(self):
        contracts = []
        for n in range(1, 21):
            task = self.task(n)
            self.assertEqual(task, build(n))
            contract = task['public_policy']['escalation_evidence_contract']
            contracts.append(contract)
            spec = task['evaluation'].get('escalation')
            if spec:
                row = next(b for b in contract['barriers'] if b['blocker_code'] == spec['barrier_code'])
                self.assertEqual([row['human_action_code']], spec['allowed_human_action_codes'])
                self.assertEqual(set(row['required_observation_tools']), set(spec['required_observation_tools']))
        self.assertTrue(all(c == contracts[0] for c in contracts))

    def run_case(self, n, mode):
        task = self.task(n)
        with tempfile.TemporaryDirectory() as directory:
            with Environment.create(task, Path(directory) / 'run.sqlite') as env:
                real = env.session()
                class Proxy:
                    def call(_, name, arguments, **kwargs):
                        arguments = dict(arguments)
                        if name == 'escalate':
                            logs = {l['event_id']: l for l in env.logs()}
                            if mode == 'missing':
                                required = 'get_consultation_reports' if n == 20 else 'check_provider_eligibility'
                                arguments['evidence_event_ids'] = [eid for eid in arguments['evidence_event_ids'] if logs[eid]['tool_name'] != required]
                            elif mode == 'stale':
                                threshold = max(l['sequence'] for l in env.logs() if l['environment_events'])
                                arguments['evidence_event_ids'] = [eid for eid in arguments['evidence_event_ids'] if logs[eid]['sequence'] < threshold]
                            elif mode == 'wrong_action':
                                arguments['human_action_code'] = 'coordinate_exception'
                        return real.call(name, arguments, **kwargs)
                env.session = lambda: Proxy()
                run_reference(task, env)
                return grade(task, env.snapshot(), env.logs(), env.runtime_info())

    def test_valid_and_missing_evidence_for_every_barrier(self):
        for n in (7, 8, 14, 19, 20):
            with self.subTest(task=n):
                self.assertTrue(self.run_case(n, 'valid')['success'])
                result = self.run_case(n, 'missing')
                self.assertFalse(result['success'])
                self.assertFalse(result['outcomes'][0]['predicates']['evidence_supports_barrier'])

    def test_pre_change_evidence_is_insufficient(self):
        for n in (19, 20):
            with self.subTest(task=n):
                result = self.run_case(n, 'stale')
                self.assertFalse(result['success'])
                self.assertFalse(result['outcomes'][0]['predicates']['evidence_supports_barrier'])

    def test_wrong_mapped_action_fails(self):
        result = self.run_case(8, 'wrong_action')
        self.assertFalse(result['success'])
        self.assertFalse(result['outcomes'][0]['predicates']['human_action_allowed'])
