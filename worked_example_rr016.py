"""Reproduce the bundled RR_016 worked example. Scripted demonstration, not a model baseline."""
import argparse
import json
from pathlib import Path
from referral_recover import Environment
from referral_recover.grader import grade


def demonstrate(context, call, stop_after_rejection=False):
    """Uses only public context and responses; no authored provider or slot IDs."""
    rid = context['referral_id']
    ref = call('get_referral', {'referral_id': rid})['data']
    slots = call('find_appointment_slots', {'referral_id': rid, 'provider_id': ref['provider_id']})['data']['slots']
    constraints = ref['scheduling_constraints']
    slot = next(s for s in slots if
                ('earliest' not in constraints or s['start_at'] >= constraints['earliest']) and
                ('latest' not in constraints or s['start_at'] <= constraints['latest']))
    args = {'referral_id': rid, 'slot_id': slot['slot_id']}
    rejected = call('schedule_appointment', args)
    assert not rejected['ok'] and rejected['error']['code'] == 'AUTHORIZATION_INVALID'
    if stop_after_rejection:
        return
    assert call('get_coverage', {'referral_id': rid})['ok']
    assert call('check_authorization', {'referral_id': rid})['ok']
    assert call('request_authorization', {'referral_id': rid})['ok']
    assert call('schedule_appointment', args)['ok']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    task = json.loads((root/'tasks/eval/RR_016.json').read_text())
    for mode in ['success', 'stop_after_rejection']:
        dest = a.output/mode
        dest.mkdir()
        transcript = []
        with Environment.create(task, dest/'environment.sqlite', max_tool_calls=30) as env:
            session = env.session()
            context = session.context()
            (dest/'public_context.json').write_text(json.dumps({'context':context,'tools':session.definitions()},indent=2)+'\n')
            def call(name, arguments):
                response = session.call(name, arguments, call_id=f'worked-{len(transcript)+1}')
                transcript.append({'tool':name,'arguments':dict(arguments),'response':response})
                return response
            demonstrate(context, call, mode=='stop_after_rejection')
            score = grade(task,env.snapshot(),env.logs(),env.runtime_info())
            assert score['success'] == (mode=='success'), score
            assert not score['hard_violations']
            env.export(dest)
            (dest/'public_transcript.json').write_text(json.dumps(transcript,indent=2)+'\n')
            (dest/'grade.json').write_text(json.dumps(score,indent=2)+'\n')
        # SQLite is reproducible and unnecessary for the published evidence.
        for f in dest.glob('environment.sqlite*'):
            f.unlink()
        print(mode, score['success'], len(transcript))
    good=json.loads((a.output/'success/public_transcript.json').read_text())
    bad=json.loads((a.output/'stop_after_rejection/public_transcript.json').read_text())
    assert bad==good[:len(bad)], 'Failure must share the exact successful prefix.'

if __name__=='__main__':
    main()
