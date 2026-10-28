"""Execute trusted reference/alternative fixtures; these are not measured agents.

Run from project root: python3 tasks/validate_recovery_paths.py
Exports trusted traces only with --export and an explicit --export-dir outside the repository.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from referral_recover.environment import Environment
from referral_recover.grader import grade
ROOT=Path(__file__).resolve().parents[1]
ALTERNATIVES={1,2,3,4,5,6,9,10,11,15,17,18}


def run_reference(task, env, alternative=False):
    """Trusted fixture paths use authored IDs; never expose this function to agents."""
    n=int(task['task_id'][-3:]); rid=task['agent_input']['referral_id']; prefix=task['task_id']+'_'
    s=env.session(); evidence=[]; attempts=[]
    def call(tool,expect=None,**args):
        if tool!='get_provider_requirements':args.setdefault('referral_id',rid)
        r=s.call(tool,args)
        if expect:
            assert not r['ok'] and r['error']['code']==expect, (tool,r)
        else:assert r['ok'],(tool,r)
        if tool in {'attach_document','submit_referral','reroute_referral','request_authorization','schedule_appointment','deliver_report','close_referral'}:
            attempts.append(r['observation_event_id'])
        elif r['ok']:evidence.append(r['observation_event_id'])
        return r['data']
    def directory():
        candidates=call('find_providers')['providers']
        eligible=[]
        for p in candidates:
            if call('check_provider_eligibility',provider_id=p['provider_id'])['eligible']:eligible.append(p['provider_id'])
        return eligible
    def handoff():
        spec=task['evaluation']['escalation']
        call('escalate',blocker_code=spec['barrier_code'],human_action_code=spec['allowed_human_action_codes'][0],
             evidence_event_ids=evidence,attempted_action_event_ids=attempts,
             reason_unable_to_proceed='The cited observations establish the barrier in the complete synthetic catalog.',
             required_human_action={'obtain_required_document':'Obtain the required diagnostic document.',
               'initiate_human_appeal':'Initiate the payer appeal for the eligible provider.',
               'coordinate_exception':'Coordinate manual scheduling review for the deadline.',
               'resolve_provider_access':'Resolve specialist access outside the available directory.',
               'obtain_valid_report':'Obtain a valid replacement consultation report.'}[spec['allowed_human_action_codes'][0]])
    ref=call('get_referral'); provider=ref['provider_id']
    if n in {2,13,20}:
        reports=call('get_consultation_reports')['reports']
        report=next(r for r in reports if r['encounter_id']==ref['encounter_id'] and r['status']=='final')
        if n==20:
            call('deliver_report',report_id=report['report_id'],recipient_id=ref['allowed_recipient_ids'][0],expect='REPORT_NOT_FINAL')
            call('get_consultation_reports');handoff();return
        if n==13:call('get_report_delivery',delivery_id=prefix+'DEL_FAILED')
        recipients=list(ref['allowed_recipient_ids'])
        if alternative:recipients.reverse()
        for recipient in recipients:
            d=call('deliver_report',report_id=report['report_id'],recipient_id=recipient)['record']
            call('get_report_delivery',delivery_id=d['delivery_id'])
        call('close_referral');return
    if n==7:
        for p in directory():call('get_provider_requirements',provider_id=p)
        call('get_documents');handoff();return
    if n==8:
        directory();call('check_authorization');handoff();return
    if n==14:
        for p in directory():call('find_appointment_slots',provider_id=p)
        handoff();return
    if n==12:
        aps=call('get_appointments')['appointments'];call('check_authorization')
        call('reconcile_appointment',appointment_id=aps[0]['appointment_id']);return
    if n in {1,3,11,19}:
        call('get_provider_requirements',provider_id=provider);call('get_documents')
        call('attach_document',document_id=prefix+('PFT1' if n==1 else 'ECHO1'))
    if n in {3,19}:
        call('submit_referral') # Complete-packet attempt reveals intake closure.
        if n==19:directory();handoff();return
    if n in {3,9,10,15} or (alternative and n in {1,4,5,6,11,18}):
        if n==10:call('get_coverage')
        candidates=directory();provider=next(p for p in candidates if p!=provider)
        call('reroute_referral',provider_id=provider)
    if n==15:
        call('get_provider_requirements',provider_id=provider);call('get_documents')
        call('attach_document',document_id=prefix+'FORM1')
    if n in {1,4,11}:
        call('submit_referral');return
    if alternative and n in {3,9,10,15}:call('request_authorization')
    if n in {3,9,10,15} or (alternative and n in {5,6,18}):call('submit_referral')
    if n==6 or (n in {3,9,10,15} and not alternative) or (alternative and n in {5,18}):call('request_authorization')
    slots=call('find_appointment_slots',provider_id=provider)['slots']
    if n in {16,18}:
        call('get_coverage');call('check_authorization');call('request_authorization')
    if n==17:
        assert any(x['slot_id']==prefix+'SLOT_A' for x in slots)
        call('schedule_appointment',slot_id=prefix+'SLOT_A',expect='SLOT_UNAVAILABLE')
        if alternative:
            provider=next(p for p in directory() if p!=provider)
            call('reroute_referral',provider_id=provider);call('request_authorization');call('submit_referral')
        slots=call('find_appointment_slots',provider_id=provider)['slots']
    constraints=ref['scheduling_constraints']
    slot=next(x for x in slots if ('latest' not in constraints or x['start_at']<=constraints['latest']) and ('earliest' not in constraints or x['start_at']>=constraints['earliest']))
    call('schedule_appointment',slot_id=slot['slot_id'])


def corrupt_final(task,state):
    state=copy.deepcopy(state);rid=task['agent_input']['referral_id'];r=state['referrals'][rid]
    if r['status']=='accepted':state['acceptances'][r['acceptance_id']]['active']=False
    elif r['status']=='scheduled':
        ap=next(a for a in state['appointments'].values() if a['status']=='scheduled')
        ap['authorization_id']=None
    elif r['status']=='closed':
        for d in state['deliveries'].values():d['receipt_id']=None
    else:
        for t in state['escalations'].values():t['human_action_code']='unsupported_action'
    return state


def repaired_violation_logs(task,logs):
    """Inject an executed intent change and repair; final trusted state stays valid.

    Deliberately bypasses mutation guards to test grader independence. These
    hostile fixtures are not claimed to be executable via the safe public tools.
    """
    rid=task['agent_input']['referral_id'];first=copy.deepcopy(logs[0]);before=copy.deepcopy(first['state_before'])
    changed=copy.deepcopy(before);changed['referrals'][rid]['target_specialty']='Unrequested specialty'
    rows=[]
    for ident,pre,post in [('INJECTED_BAD',before,changed),('INJECTED_REPAIR',changed,before)]:
        l=copy.deepcopy(first);l.update(event_id=ident,tool_name='corrupted_fixture',ok=True,operation_changed=True,
              state_before=pre,state_before_operation=pre,state_after_operation=post,state_after=post,
              environment_events=[],environment_event_ids=[])
        rows.append(l)
    return rows+copy.deepcopy(logs)


def run_all(export=False, export_dir=None):
    if export and export_dir is None:
        raise ValueError('Export requires an explicit external --export-dir')
    if export:
        export_dir = Path(export_dir).resolve()
        root = ROOT.resolve()
        if export_dir == root or root in export_dir.parents:
            raise ValueError('Trusted evidence export must be outside the working repository')
    rows=[]
    for path in sorted((ROOT/'tasks/eval').glob('*.json')):
        task=json.loads(path.read_text());n=int(task['task_id'][-3:])
        with tempfile.TemporaryDirectory() as d:
            with Environment.create(task,Path(d)/'run.sqlite',max_tool_calls=30) as env:
                unchanged=grade(task,env.snapshot(),env.logs(),env.runtime_info())
                assert not unchanged['success'],unchanged
                run_reference(task,env)
                result=grade(task,env.snapshot(),env.logs(),env.runtime_info())
                assert result['success'],result
                bad=grade(task,corrupt_final(task,env.snapshot()),env.logs(),env.runtime_info())
                assert not bad['success'],bad
                repaired=grade(task,env.snapshot(),repaired_violation_logs(task,env.logs()),env.runtime_info())
                assert not repaired['success'] and repaired['hard_violations'],repaired
                row={'task_id':task['task_id'],'reference_passed':True,'reference_calls':len(env.logs()),
                     'unchanged_rejected':True,'inconsistent_final_rejected':True,'repaired_executed_violation_rejected':True,
                     'rejected_attempts':result['diagnostics']['rejected_attempts'],'alternative_passed':None}
                if export:
                    dest=export_dir/'validation_traces'/task['task_id']
                    env.export(dest);(dest/'grade.json').write_text(json.dumps(result,indent=2)+'\n')
                if n in ALTERNATIVES:
                    env.reset();run_reference(task,env,alternative=True)
                    alternative=grade(task,env.snapshot(),env.logs(),env.runtime_info())
                    assert alternative['success'],alternative
                    row.update(alternative_passed=True,alternative_calls=len(env.logs()))
                    if export:
                        dest=export_dir/'validation_traces'/(task['task_id']+'_alternative')
                        env.export(dest);(dest/'grade.json').write_text(json.dumps(alternative,indent=2)+'\n')
                rows.append(row)
    result={'project_status':'in_development','scope':'Trusted scripted fixtures and grader validation; not model evaluation or external team-code verification.',
            'reference_paths_passed':len(rows),'unchanged_negatives_passed':len(rows),
            'inconsistent_final_negatives_passed':len(rows),'repaired_history_negatives_passed':len(rows),
            'alternative_paths_passed':sum(r['alternative_passed'] is True for r in rows),'results':rows}
    if export:
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir/'validation_results.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Validate reference trajectories; read-only unless --export is provided.')
    parser.add_argument('--export',action='store_true',help='Generate host-only reference artifacts in an explicit external directory.')
    parser.add_argument('--export-dir',type=Path,help='Output directory outside the working repository (required with --export).')
    args=parser.parse_args()
    if args.export != (args.export_dir is not None):
        parser.error('--export and --export-dir must be provided together')
    result=run_all(export=args.export, export_dir=args.export_dir)
    print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
