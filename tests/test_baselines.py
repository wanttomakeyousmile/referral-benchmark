"""Public-interface smoke tests. Development tasks only; no tuning on eval traces."""
import json
import tempfile
import unittest
from pathlib import Path

from referral_recover.baselines import do_nothing, fixed_workflow
from referral_recover.environment import Environment

ROOT = Path(__file__).resolve().parents[1]


class RestrictedSession:
    """Reject attempts to use trusted host/export/fixture APIs as a controller."""
    def __init__(self, session):
        self.context = session.context
        self.call = session.call


class BaselineSmokeTests(unittest.TestCase):
    def test_do_nothing_uses_zero_tools_and_does_not_modify_state(self):
        task = json.loads((ROOT/'tasks/dev/DEV_001.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            with Environment.create(task, Path(directory)/'trial.sqlite') as env:
                before = env.snapshot()
                stop = do_nothing(RestrictedSession(env.session()))
                self.assertEqual(env.logs(), [])
                self.assertEqual(env.snapshot(), before)
                self.assertIsNone(stop['report'])

    def test_fixed_workflow_all_four_development_cases(self):
        for task_path in sorted((ROOT/'tasks/dev').glob('*.json')):
            with self.subTest(task=task_path.stem), tempfile.TemporaryDirectory() as directory:
                task = json.loads(task_path.read_text())
                with Environment.create(task, Path(directory)/'trial.sqlite') as env:
                    result = fixed_workflow(RestrictedSession(env.session()))
                    self.assertEqual(env.snapshot()['referrals'][task['agent_input']['referral_id']]['status'],
                                     task['evaluation']['expected_status'])
                    self.assertLessEqual(env.runtime_info()['tool_attempts'],30)
                    self.assertFalse(any(l['error_code'] for l in env.logs()))
                    self.assertIsInstance(result.get('report'),dict)
                    self.assertEqual(result['report']['final_status_claim'],task['evaluation']['expected_status'])

    def test_fixed_workflow_repeats_state_and_tool_decisions_on_dev(self):
        task=json.loads((ROOT/'tasks/dev/DEV_002.json').read_text())
        results=[]
        with tempfile.TemporaryDirectory() as directory:
            for i in range(2):
                with Environment.create(task,Path(directory)/f'trial{i}.sqlite') as env:
                    fixed_workflow(RestrictedSession(env.session()))
                    results.append((env.snapshot(), [(l['tool_name'], l['arguments'], l['ok']) for l in env.logs()]))
        self.assertEqual(*results)

    def test_isolated_trials_have_unique_run_ids(self):
        task=json.loads((ROOT/'tasks/dev/DEV_001.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            ids=[]
            for i in range(2):
                with Environment.create(task,Path(directory)/f'isolated{i}.sqlite') as env:
                    ids.append(env.runtime_info()['run_id'])
                    do_nothing(RestrictedSession(env.session()))
            self.assertNotEqual(ids[0], ids[1])


if __name__ == '__main__': unittest.main()
