"""Local integration demonstration, not a general agent or scored baseline."""
import argparse
import json
from pathlib import Path

from referral_recover import Environment
from referral_recover.grader import grade


def run_agent(context, definitions, call, mode):
    """Replace this function with your agent. Only public inputs enter here."""
    names = {tool['name'] for tool in definitions}
    assert 'get_referral' in names
    referral_id = context['referral_id']
    result = call('get_referral', {'referral_id': referral_id})
    if not result['ok']:
        raise RuntimeError(result['error'])
    if mode == 'accept-demo':
        # Deliberately limited to the documented RR_004 integration example.
        # This is not a strategy for the other tasks or a performance claim.
        result = call('submit_referral', {'referral_id': referral_id})
        if not result['ok']:
            raise RuntimeError(result['error'])
    return 'Integration demonstration finished.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['read-only', 'accept-demo'], default='accept-demo')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    task = json.loads((root / 'tasks/eval/RR_004.json').read_text())
    # Host-only code loads hidden task state and owns the evaluator.
    args.output.mkdir(parents=True, exist_ok=False)
    transcript = []
    with Environment.create(task, args.output / 'environment.sqlite', max_tool_calls=30) as env:
        session = env.session()
        context, definitions = session.context(), session.definitions()
        (args.output / 'public_context.json').write_text(json.dumps(
            {'context': context, 'tools': definitions}, indent=2) + '\n')

        def call(name, arguments):
            response = session.call(name, arguments, call_id=f'example-{len(transcript)+1}')
            transcript.append({'tool': name, 'arguments': arguments, 'response': response})
            return response

        report = run_agent(context, definitions, call, args.mode)
        (args.output / 'public_transcript.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in transcript))
        (args.output / 'agent_report.txt').write_text(report + '\n')
        env.export(args.output)
        result = grade(task, env.snapshot(), env.logs(), env.runtime_info())
        (args.output / 'grade.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'task_id': task['task_id'], 'mode': args.mode,
                      'success': result['success'], 'output': str(args.output)}))
    expected = args.mode == 'accept-demo'
    if result['success'] is not expected:
        raise SystemExit('Unexpected integration result. Inspect grade.json.')


if __name__ == '__main__':
    main()
