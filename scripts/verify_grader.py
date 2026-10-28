import sys,json,tempfile,copy,argparse
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);a=parser.parse_args()
root=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(root),str(root/'tasks')]
from referral_recover import Environment
from referral_recover.grader import grade
from validate_recovery_paths import run_reference,run_all
j=lambda p,x:p.write_text(json.dumps(x,indent=2)+'\n')
summary=run_all(export=True,export_dir=out/'trusted_fixtures')
rows=[]
for n,mode in [(6,'rejected_then_recovered'),(6,'synthetic_executed_bad_booking'),(17,'direct_backup'),(16,'direct_booking_repair'),(18,'direct_booking_repair'),(3,'event_gate_isolation'),(19,'event_gate_isolation'),(20,'event_gate_isolation')]:
 t=json.loads((root/f'tasks/eval/RR_{n:03}.json').read_text());rid=t['agent_input']['referral_id']
 with tempfile.TemporaryDirectory() as d, Environment.create(t,Path(d)/'run.sqlite') as env:
  s=env.session()
  def call(tool,**args):return s.call(tool,{'referral_id':rid,**args})
  if mode=='rejected_then_recovered':
   r=call('schedule_appointment',slot_id='RR_006_SLOT_A');assert r['error']['code']=='AUTHORIZATION_INVALID'
   run_reference(t,env)
  elif mode=='direct_backup':
   ref=call('get_referral')['data'];slots=call('find_appointment_slots',provider_id=ref['provider_id'])['data']['slots']
   backup=next(x for x in slots if x['slot_id'].endswith('SLOT_BACKUP'))
   assert call('schedule_appointment',slot_id=backup['slot_id'])['ok']
   assert 'SLOT_LOST' not in env.runtime_info()['fired']
  elif mode=='direct_booking_repair':
   ref=call('get_referral')['data'];slot=f'RR_{n:03}_SLOT_A'
   assert call('schedule_appointment',slot_id=slot)['error']['code']=='AUTHORIZATION_INVALID'
   call('check_authorization');call('request_authorization');call('find_appointment_slots',provider_id=ref['provider_id'])
   assert call('schedule_appointment',slot_id=slot)['ok']
  else:run_reference(t,env)
  logs=env.logs();state=env.snapshot();runtime=env.runtime_info();baseline=grade(t,state,logs,runtime);assert baseline['success']
  if mode=='synthetic_executed_bad_booking':
   logs=copy.deepcopy(logs);booking=next(l for l in logs if l['tool_name']=='schedule_appointment')
   for auth in booking['state_before_operation']['authorizations'].values():auth['status']='denied'
  elif mode=='event_gate_isolation':
   logs=copy.deepcopy(logs)
   for l in logs:l['environment_events']=[];l['environment_event_ids']=[]
  score=grade(t,state,logs,runtime)
  expected=mode not in {'synthetic_executed_bad_booking','event_gate_isolation'};assert score['success']==expected,score
  dest=out/f'RR_{n:03}_{mode}';dest.mkdir(exist_ok=True)
  j(dest/'evidence.json',{'kind':'synthetic grader-input fixture, not a publicly executable trajectory' if not expected else 'executed scripted fixture; not a model or independent human run','task_id':t['task_id'],'logs':logs,'state':state,'runtime':runtime,'baseline_grade':baseline,'grade':score})
  rows.append({'task':t['task_id'],'variant':mode,'success':score['success'],'hard_violations':score['hard_violations'],'missing_events':score['missing_required_events'],'path':dest.name+'/evidence.json'})
events=[]
for p in sorted((root/'tasks/eval').glob('*.json')):
 t=json.loads(p.read_text());events.append({'task':t['task_id'],'required_event_ids':t['evaluation'].get('required_event_ids',[]),'post_event_evidence':t['evaluation'].get('escalation',{}).get('require_observations_after_barrier_event',False),'task_constraints':t['evaluation']['task_constraints'],'events':t['environment'].get('events',[])})
j(out/'event_and_constraint_map.json',events);j(out/'targeted_results.json',rows)
print(json.dumps({'fixture_counts':{k:v for k,v in summary.items() if k!='results'},'targeted_results':rows},indent=2))
