"""Small local CLI for scripted tool demonstrations; no model/API calls."""
import argparse
import json
from pathlib import Path
from .environment import Environment

def run_demo(task_path, output):
    task=json.loads(Path(task_path).read_text())
    if task['task_id'] not in {'DEV_001','DEV_002','DEV_003','DEV_004'}:
        raise ValueError('demo supports DEV_001–DEV_004; run tasks/validate_recovery_paths.py for evaluation fixtures')
    directory=Path(output); directory.mkdir(parents=True,exist_ok=True)
    with Environment.create(task,directory/'environment.sqlite',max_tool_calls=30) as env:
        session=env.session(); rid=task['agent_input']['referral_id']; n=0
        def call(name,**args):
            nonlocal n
            n+=1; response=session.call(name,args,call_id=f'CALL_{n:03d}')
            print(json.dumps({'tool':name,**response}))
            if not response['ok']: raise RuntimeError(response['error'])
            return response
        call('get_referral',referral_id=rid)
        if task['task_id']=='DEV_003':
            call('get_consultation_reports',referral_id=rid)
            d=call('deliver_report',referral_id=rid,report_id='REPORT_GOOD',recipient_id='PCP1')['data']['record']
            call('get_report_delivery',referral_id=rid,delivery_id=d['delivery_id'])
            call('close_referral',referral_id=rid)
        elif task['task_id']=='DEV_004':
            evidence=call('get_documents',referral_id=rid)['observation_event_id']
            call('escalate',referral_id=rid,blocker_code='required_document_unavailable',evidence_event_ids=[evidence],
                 attempted_action_event_ids=[],reason_unable_to_proceed='Required echocardiogram is unavailable in accessible records.',
                 human_action_code='obtain_required_document',required_human_action='Obtain the required echocardiogram report and add it to the records.')
        else:
            call('get_provider_requirements',provider_id='CARD_A')
            call('get_documents',referral_id=rid)
            call('attach_document',referral_id=rid,document_id='ECHO1')
            call('submit_referral',referral_id=rid)
            if task['task_id']=='DEV_002':
                call('find_providers',referral_id=rid)
                call('check_provider_eligibility',referral_id=rid,provider_id='CARD_B')
                call('reroute_referral',referral_id=rid,provider_id='CARD_B')
                call('request_authorization',referral_id=rid)
                call('submit_referral',referral_id=rid)
                call('find_appointment_slots',referral_id=rid,provider_id='CARD_B')
                call('schedule_appointment',referral_id=rid,slot_id='SLOT_B')
        call('get_referral',referral_id=rid)
        env.export(directory)
        observed=env.snapshot()['referrals'][rid]['status']
        expected=[o['terminal_status'] for o in task['evaluation'].get('allowed_outcomes',[])]
        if not expected: expected=[task['evaluation']['expected_status']] # Legacy DEV-only demo metadata
        # A demonstration assertion, intentionally NOT a complete benchmark grader.
        summary={'task_id':task['task_id'],'observed_status':observed,'allowed_statuses':expected,
                 'demo_status_check_passed':observed in expected,'tool_attempts':env.runtime_info()['tool_attempts']}
        (directory/'demo_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary))
        if observed not in expected: raise RuntimeError('Demo state assertion failed')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    demo=sub.add_parser('demo');demo.add_argument('--task',default='tasks/dev/DEV_001.json');demo.add_argument('--output',required=True)
    reset=sub.add_parser('reset');reset.add_argument('--db',required=True)
    grading=sub.add_parser('grade',help='Grade trusted evaluation exports')
    grading.add_argument('--task',required=True);grading.add_argument('--run',required=True)
    args=parser.parse_args()
    if args.command=='demo':run_demo(args.task,args.output)
    elif args.command=='grade':
        from .grader import grade
        directory=Path(args.run)
        result=grade(json.loads(Path(args.task).read_text()),json.loads((directory/'final_state.json').read_text()),
                     [json.loads(line) for line in (directory/'actions.jsonl').read_text().splitlines() if line],
                     json.loads((directory/'runtime.json').read_text()))
        print(json.dumps(result,indent=2))
        raise SystemExit(0 if result['success'] is True else 2 if result['success'] is None else 1)
    else:
        with Environment(args.db) as env:
            session=env.reset()
            print(json.dumps({'reset':True,'agent_context':session.context(),'runtime':env.runtime_info()}))
if __name__=='__main__':main()
