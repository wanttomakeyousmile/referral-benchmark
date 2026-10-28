"""Structural/load checks only; does not claim successful trajectories or grader validation."""
import argparse,collections,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from referral_recover.environment import Environment, validate_task
ROOT=Path(__file__).parent
PREDICATES={'packet_complete','provider_eligible','acceptance_valid','authorization_valid','appointment_valid','no_duplicate_appointment','current_report_matches','all_required_receipts','closure_valid','escalation_ticket_valid','barrier_true','evidence_supports_barrier','human_action_allowed'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional detailed JSON report destination")
    return validate_all(parser.parse_args().output)

def validate_all(output=None):
 try:
  import jsonschema
 except ImportError:
  jsonschema=None
 schema=json.loads((ROOT/'evaluation_task.schema.json').read_text())
 tasks=[json.loads(p.read_text()) for p in sorted((ROOT/'eval').glob('*.json'))]
 assert len(tasks)==20
 assert {t['task_id'] for t in tasks}=={f'RR_{n:03}' for n in range(1,21)}
 counts=collections.Counter();rows=[]
 for t in tasks:
  if jsonschema: jsonschema.validate(t,schema)
  validate_task(t)
  ev=t['evaluation'];counts[t['metadata']['difficulty']]+=1
  assert t['metadata']['split']=='eval' and t['metadata']['development_distinction']
  assert ev['allowed_outcomes']
  assert all(p['name'] in PREDICATES for o in ev['allowed_outcomes'] for p in o['required_predicates'])
  assert ev['escalation_required']==all(o['terminal_status']=='escalated' for o in ev['allowed_outcomes'])
  if ev['escalation_required']:assert ev['escalation']['allowed_human_action_codes'] and ev['escalation']['required_observation_tools']
  assert set(ev.get('required_event_ids',[]))<={e['event_id'] for e in t['environment']['events']}
  assert t['authoring']['reference_outline'] and len(t['authoring']['negative_checks'])>=3
  with tempfile.TemporaryDirectory() as d:
   with Environment.create(t,Path(d)/'trial.sqlite') as env:
    ctx=env.session().context()
    assert 'evaluation' not in ctx and 'authoring' not in ctx and 'environment' not in ctx
    assert env.snapshot()
  rows.append({'task_id':t['task_id'],'result':'structural checks and isolated environment creation passed','trajectory_executed':False})
 assert counts=={'easy':7,'medium':7,'hard':6}
 assert sum(t['evaluation']['escalation_required'] for t in tasks)==5
 result={'json_schema_envelope_checked':jsonschema is not None,'tasks_checked':20,'difficulty_counts':dict(counts),'escalation_cases':5,'scope':'schema/metadata/record-reference validation and isolated environment creation; no agent runs or predicate grader tests','results':rows}
 if output is not None:
  output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
  output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
if __name__=='__main__':main()
