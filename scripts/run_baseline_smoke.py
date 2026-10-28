"""Run LOCAL baseline smoke checks in isolated SQLite trials.

The fixed_workflow controller is supported here only on development cases.
The evaluation split supports do_nothing only, to check grader rejection of
unchanged initial states. To evaluate another controller, use the session and
grading interface documented in EXTERNAL_AGENT_QUICKSTART.md.
The do-nothing evaluation sanity sweep is an explicitly nonscored grader check.
No scored experiment claims, paired bootstrap, LLM, or finalized usage costs.
"""
import argparse
import json
import time
from pathlib import Path

from referral_recover.baselines import BASELINES
from referral_recover.environment import Environment
from referral_recover.grader import grade
from referral_recover.catalog import MUTATIONS


class PublicControllerInterface:
    """Surface only the advertised methods to local smoke controllers.

    This limits accidental host access; it is NOT an adversarial Python sandbox.
    """
    __slots__ = ('context', 'call')
    def __init__(self, session):
        self.context = session.context
        self.call = session.call


def run_one(task_path, name, dest):
    task = json.loads(Path(task_path).read_text())
    dest.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    with Environment.create(task, dest/'environment.sqlite', max_tool_calls=30) as env:
        session = env.session()
        outcome = BASELINES[name](PublicControllerInterface(session))
        env.export(dest)
        final = env.snapshot()
        logs = env.logs()
        runtime = env.runtime_info()
        rid = session.context()['referral_id']
        actual_status = final['referrals'][rid]['status']
        if task['task_id'].startswith('RR_'):
            graded = grade(task, final, logs, runtime)
            success = graded.get('success')
            mode = 'nonscored_grader_sanity'
            (dest/'grade.json').write_text(json.dumps(graded, indent=2)+'\n')
        else:
            # DEV_*.json are legacy cases with an expected_status, not the final
            # 20-task evaluator contract. This is intentionally NOT grader success.
            success = actual_status == task['evaluation']['expected_status']
            mode = 'development_status_only'
        result = {
            'task_id': task['task_id'], 'controller': name, 'mode': mode,
            'observation': actual_status, 'expected_status_dev_only': task['evaluation'].get('expected_status'),
            'status_check_passed_dev_only': success if mode == 'development_status_only' else None,
            'grader_success_eval_sanity_only': success if mode == 'nonscored_grader_sanity' else None,
            'logical_tool_attempts': runtime['tool_attempts'],
            'attempted_mutations': sum(l['tool_name'] in MUTATIONS for l in logs),
            'effective_mutations': sum(bool(l['operation_changed']) for l in logs),
            'rejected_attempts': sum(not l['ok'] for l in logs),
            'premature_attempts': sum(bool(l.get('premature')) for l in logs),
            'executed_violations': None if mode == 'development_status_only' else len(graded.get('hard_violations', [])),
            'stop_reason': outcome['stop_reason'],
            'elapsed_wall_seconds': round(time.perf_counter() - started, 6),
            'input_tokens': None, 'output_tokens': None, 'api_cost_usd': None,
            'report_emitted': outcome.get('report') is not None,
        }
        (dest/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', choices=BASELINES, required=True)
    p.add_argument('--split', choices=('dev','eval-do-nothing-sanity'), required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    if args.split == 'eval-do-nothing-sanity' and args.baseline != 'do_nothing':
        p.error('The eval-do-nothing-sanity split supports only do_nothing; use --split dev for fixed_workflow')
    src = Path('tasks/dev' if args.split == 'dev' else 'tasks/eval')
    files = sorted(src.glob('*.json'))
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    rows = [run_one(task, args.baseline, root/task.stem) for task in files]
    result = {'mode': args.split, 'controller': args.baseline, 'trials': rows,
              'count': len(rows), 'passes': sum(bool(x['status_check_passed_dev_only'] if args.split=='dev'
                        else x['grader_success_eval_sanity_only']) for x in rows)}
    (root/'manifest.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'controller': args.baseline, 'mode':args.split,
                      'runs': len(rows), 'passes': result['passes'], 'output': str(root)}))


if __name__ == '__main__': main()
