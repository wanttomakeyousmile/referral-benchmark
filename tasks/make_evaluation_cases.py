"""Author/rebuild 20 synthetic evaluation specifications; does not execute agents."""
import copy
import json
from pathlib import Path
from make_development_cases import base, cases
ROOT=Path(__file__).parent
C=copy.deepcopy
TITLES=['Missing diagnostic document','Current report and multiple recipients','Repair reveals rerouting','Complete packet needs submission','Constraint-compliant slot selection','Provider-specific authorization','No qualifying document available','Human-only appeal','Known intake closure','Authoritative coverage conflict','Document linkage and status','Existing appointment reconciliation','Failed delivery retry','No feasible appointment','New provider changes requirements','Coverage invalidates approval','Selected slot becomes unavailable','Authorization expires before booking','Routing options exhausted','Report withdrawn without replacement']
DIFF=['easy', 'medium', 'hard', 'easy', 'easy', 'easy', 'easy', 'easy', 'medium', 'medium', 'medium', 'medium', 'medium', 'medium', 'hard', 'hard', 'easy', 'hard', 'hard', 'hard']
BLOCK=['missing_required_document','report_delivery_pending','missing_required_document','unsubmitted_complete_packet','scheduling_pending','missing_authorization','required_document_unavailable','authorization_denied_human_appeal','provider_not_accepting','coverage_conflict','missing_required_document','appointment_record_mismatch','report_delivery_failed','no_feasible_slot','provider_not_accepting','scheduling_pending','scheduling_pending','scheduling_pending','missing_required_document','report_delivery_pending']
TAGS=[['documentation'],['report_delivery','closure'],['documentation','routing','authorization','invalidation'],['documentation'],['scheduling'],['authorization','scheduling'],['documentation','escalation'],['authorization','escalation'],['routing','authorization'],['coverage','routing','authorization'],['documentation'],['scheduling','reconciliation'],['report_delivery','closure'],['scheduling','escalation'],['routing','documentation','authorization','invalidation'],['coverage','authorization','invalidation'],['scheduling','invalidation'],['authorization','invalidation'],['routing','documentation','escalation','invalidation'],['report_delivery','escalation','invalidation']]
NOVEL=['Different required document and irrelevant available evidence','Two required recipients plus superseded version and encounter distractor','Two routing alternatives, one out of network, after document repair','All documents initially attached; attachment replay cannot solve submission','Multiple slots include one outside the allowed window','Complete accepted packet but no current-provider approval','Unavailable required type plus available nonqualifying substitutes','Observed payer denial is explicitly human-only','Closure known at start, with invalid and valid alternative providers','Payer registry conflicts with cached intake coverage','Same-type draft and wrong-encounter distractors','Legitimate existing booking must be reconciled without rebooking','Existing failed delivery must be retried and receipt verified','Available slots exist but none meet the public deadline','Alternate provider requires a newly discovered additional document','New payer coverage invalidates current approval after slot discovery or before direct booking','First attempt to book the observed SLOT_A invalidates it immediately before booking','Slot discovery or direct booking expires the existing authorization','Repair reveals intake closure and directory contains no eligible substitute','Observed valid report is withdrawn immediately before its attempted delivery']

def complete(t):
 s=t['environment']['initial_state'];s['referrals'][0]['attached_document_ids']=[d['document_id'] for d in s['documents'] if d['document_id'] in ['ORDER1','ECHO1']]

def accepted(t):
 complete(t);s=t['environment']['initial_state'];r=s['referrals'][0];r.update(status='accepted',rejection_codes=[],acceptance_id='ACC0')
 s['acceptances']=[dict(acceptance_id='ACC0',referral_id='R1',provider_id='CARD_A',requirements_version=1,packet_document_versions={'ORDER1':1,'ECHO1':1},active=True,issued_at='2026-08-31T10:00:00Z')]

def event(t,name,tool,changes,phase='after',**guard):
 t['environment']['events'].append(dict(event_id=name,trigger=dict(phase=phase,tool=tool,arguments_match={'referral_id':'R1'},**guard),changes=[dict(collection=c,id=i,set=v) for c,i,v in changes]))

def build(n):
 t=C(cases()[2]) if n in (2,13,20) else base()
 t['task_id']=f'RR_{n:03}';t['metadata']={'split':'eval','title':TITLES[n-1],'difficulty':DIFF[n-1],'categories':TAGS[n-1],'provenance':'Original authored synthetic evaluation specification; legacy scenario family retained where noted','development_distinction':NOVEL[n-1],'execution_validated':True}
 s=t['environment']['initial_state'];r=s['referrals'][0];p=s['providers'];docs=s['documents'];a=s['authorizations'][0]
 status='accepted' if n in (1,4,11) else 'closed' if n in (2,13) else 'escalated' if n in (7,8,14,19,20) else 'scheduled'
 if n==1:
  for provider in p: provider['required_document_rules'][1]['document_type']='pulmonary_function_report'
  docs[1]['document_type']='pulmonary_function_report'
  docs[1]['document_id']='PFT1'
  t['public_policy']['intake_requirement_scope']='RR_001 uses a synthetic provider-specific intake requirement for an existing pulmonary-function report. Clinical appropriateness and referral intent are fixed; the agent retrieves and attaches qualifying evidence without diagnosing the patient or selecting clinical tests. This requirement is not a general cardiology guideline.'
  extra=C(docs[1]);extra.update(document_id='UNRELATED',document_type='metabolic_panel');docs.append(extra)
 if n==2:
  r['allowed_recipient_ids']=['PCP1','COORDINATOR1']
  old=C(s['reports'][0]);old.update(report_id='REPORT_V1',status='superseded');s['reports'].append(old)
  s['reports'][0].update(version=2,supersedes_report_id='REPORT_V1')
 if n in (3,9,15,19):
  extra=C(p[1]);extra.update(provider_id='CARD_C',accepted_plan_ids=['OTHER_PLAN']);p.append(extra)
  if n in (3,19):event(t,'INTAKE_CHANGE','submit_referral',[('providers','CARD_A',{'accepting_referrals':False})],phase='before',packet_complete=True)
  else:p[0]['accepting_referrals']=False;complete(t);r['rejection_codes']=['accepting_referrals']
 if n==4:complete(t);r.update(status='pending',rejection_codes=[])
 if n in (5,14,16,17,18):accepted(t)
 if n==5:
  s['slots'][0]['start_at']='2026-09-25T10:00:00Z';s['slots'][0]['end_at']='2026-09-25T10:30:00Z'
  slot=C(s['slots'][0]);slot.update(slot_id='SLOT_OK',start_at='2026-09-15T10:00:00Z',end_at='2026-09-15T10:30:00Z');s['slots'].append(slot)
 if n==6:accepted(t);s['authorizations']=[]
 if n==7:
  docs[1]['available']=False; p[1]['accepted_plan_ids']=['OTHER_PLAN']
  wrong=C(docs[1]);wrong.update(document_id='AVAILABLE_SUBSTITUTE',available=True,document_type='metabolic_panel');docs.append(wrong)
 if n==8:
  accepted(t);a.update(status='denied',human_appeal_required=True,decision_code='human_appeal_required');t['environment']['simulation']['authorization_decisions']={'CARD_A':'denied','CARD_B':'denied'}
  p[1]['accepted_plan_ids']=['OTHER_PLAN']
 if n==10:
  complete(t);r['rejection_codes']=['network_match'];s['patients'][0].update(insurance_plan_id='PLAN_B',coverage_version=2,coverage_sources=[{'source':'intake_cache','insurance_plan_id':'PLAN_A','coverage_version':1}]);p[1]['accepted_plan_ids']=['PLAN_B'];a['status']='invalidated'
 if n==11:
  s['encounters'].append(dict(encounter_id='E_OTHER',patient_id='P1',status='completed'))
  for ident,fields in [('DOC_DRAFT',{'status':'draft'}),('DOC_WRONG_VISIT',{'encounter_id':'E_OTHER'})]:
   d=C(docs[1]);d.update(document_id=ident,**fields);docs.append(d)
 if n==12:
  accepted(t);r['status']='pending';s['slots'][0]['available']=False
  s['appointments']=[dict(appointment_id='AP0',referral_id='R1',patient_id='P1',provider_id='CARD_A',slot_id='SLOT_A',status='scheduled',booked_at='2026-08-31T11:00:00Z',acceptance_id='ACC0',authorization_id='AUTH1')]
 if n==13:s['deliveries']=[dict(delivery_id='DEL_FAILED',referral_id='R1',report_id='REPORT_GOOD',report_version=1,recipient_id='PCP1',status='failed',receipt_id=None,failure_code='transport_rejected')]
 if n==14:
  r['scheduling_constraints']['latest']='2026-09-05T23:59:00Z'
 if n==15:
  p[1]['required_document_rules'].append(dict(document_type='specialist_intake_form',statuses=['signed'],linkage='referral'))
  d=C(docs[0]);d.update(document_id='FORM1',document_type='specialist_intake_form');docs.append(d)
 if n==16:
  p[0]['accepted_plan_ids'].append('PLAN_B');event(t,'COVERAGE_CHANGE','find_appointment_slots',[('patients','P1',{'insurance_plan_id':'PLAN_B','coverage_version':2})])
 if n==17:
  slot=C(s['slots'][0]);slot.update(slot_id='SLOT_BACKUP',start_at='2026-09-12T10:00:00Z',end_at='2026-09-12T10:30:00Z');s['slots'].append(slot)
  event(t,'SLOT_LOST','schedule_appointment',[('slots','SLOT_A',{'available':False})],phase='before')
  t['environment']['events'][-1]['trigger']['arguments_match']['slot_id']='SLOT_A'
 if n==18:event(t,'AUTH_EXPIRES','find_appointment_slots',[('authorizations','AUTH1',{'valid_until':'2026-09-01T09:00:00Z'})])
 if n==19:p[1]['accepting_referrals']=False
 if n==20:
  event(t,'REPORT_WITHDRAWN','deliver_report',[('reports','REPORT_GOOD',{'status':'withdrawn','available':False})],phase='before')
  t['environment']['events'][-1]['trigger']['arguments_match']['report_id']='REPORT_GOOD'
 # Shared public rules are available to every controller; hidden predicates never replace public policies.
 t['public_policy'].update(catalogs_complete=True,coverage_authority='payer_registry',allowed_recipient_semantics='Every listed recipient requires a receipt for the current matching report before closure.',failed_reads='A failed read establishes unknown state, not an unavailable resource or a human-only barrier.',booking='A booking requires current provider eligibility, complete accepted packet and current matching authorization when required.',escalation='Escalate only when observations establish a declared human-only barrier; budget exhaustion alone is not evidence.')
 t['public_policy']['encounter_context']='For pre-visit recovery, encounter-linked supporting documents represent pre-visit workup associated with the planned specialist encounter; a final supporting document does not imply that the specialist visit has occurred. Encounter linkage requires document.encounter_id == referral.encounter_id. Referral linkage requires referral.referral_id in document.related_referral_ids. Patient, availability, type and status checks also apply. Post-visit consultation reports remain tied to the completed specialist encounter and appointment.'
 if n==8:t['public_policy']['appeal_policy']='An appeal-only payer denial cannot be overridden by an administrative authorization request. Check the complete provider directory for eligible alternatives before requesting human appeal.'
 # Describe the requested workflow independently of its hidden expected outcome.
 goal_family='accepted' if n in (1,4,7,11) else 'closed' if n in (2,13,20) else 'scheduled'
 primary_goal={'accepted':'Obtain valid provider acceptance for this referral with a complete qualifying packet.','scheduled':'Recover this referral and establish a valid appointment within its stated scheduling constraints.','closed':'Deliver the current matching consultation report to every required recipient, verify receipts and close this referral.'}[goal_family]
 t['agent_input']['goal']=primary_goal+' If observations establish a declared human-only barrier that prevents this goal, create an evidence-supported human handoff under the public escalation policy; budget exhaustion alone does not justify escalation.'
 predicates=['packet_complete','provider_eligible','acceptance_valid'] if status=='accepted' else ['packet_complete','provider_eligible','acceptance_valid','authorization_valid','appointment_valid','no_duplicate_appointment'] if status=='scheduled' else ['current_report_matches','all_required_receipts','closure_valid'] if status=='closed' else ['escalation_ticket_valid','barrier_true','evidence_supports_barrier','human_action_allowed']
 ev={'task_id':t['task_id'],'expected_status':status,'allowed_outcomes':[{'outcome_id':status,'terminal_status':status,'required_predicates':[{'name':v,'args':{'referral_id':'R1'}} for v in predicates]}],'global_rules_version':'1.0','task_constraints':[],'initial_blocker_codes':[BLOCK[n-1]],'escalation_required':status=='escalated'}
 if n in (3,15,16,18,19,20):ev['required_event_ids']=[e['event_id'] for e in t['environment']['events']]
 if n==12:ev['task_constraints']=[{'name':'preserve_existing_appointment','args':{'appointment_id':'AP0'}}]
 barriers={7:('required_document_unavailable','obtain_required_document',['find_providers','check_provider_eligibility','get_documents','get_provider_requirements'],'The only eligible provider requires a final echocardiogram_report linked to the target encounter; no qualifying document is available in the complete catalog.'),8:('authorization_denied_human_appeal','initiate_human_appeal',['find_providers','check_provider_eligibility','check_authorization'],'The only eligible provider has an appeal-only authorization denial for the authoritative coverage; no eligible substitute exists in the complete directory.'),14:('no_feasible_slot','coordinate_exception',['find_providers','check_provider_eligibility','find_appointment_slots'],'Every eligible provider has zero available slots satisfying the public deadline.'),19:('no_eligible_provider','resolve_provider_access',['find_providers','check_provider_eligibility'],'After INTAKE_CHANGE every provider in the complete directory is closed or out of network.'),20:('report_unavailable_or_invalid','obtain_valid_report',['get_consultation_reports'],'After REPORT_WITHDRAWN no available final report matches target patient, encounter, referral and completed appointment.')}
 if n in barriers:
  code,action,reads,rule=barriers[n];ev['escalation']={'barrier_code':code,'allowed_human_action_codes':[action],'required_observation_tools':reads,'barrier_definition':rule,'require_observations_after_barrier_event':n in (19,20),'allow_empty_attempted_actions':True}
 t['public_policy']['human_action_codes']=['obtain_required_document','initiate_human_appeal','coordinate_exception','resolve_provider_access','obtain_valid_report']
 t['public_policy']['escalation_evidence_contract']=json.loads((ROOT/'escalation_evidence_policy.json').read_text())
 if n in (16,18):
  t['environment']['events'][0]['alternative_triggers']=[{'phase':'before','tool':'schedule_appointment','arguments_match':{'referral_id':'R1'}}]
  ev.pop('required_event_ids',None)
 t['evaluation']=ev
 t['authoring']={'reference_outline':reference(n),'negative_checks':negative(n),'required_extensions':[],'validation_status':'Corrected specification; see docs/validation_results.json for executed fixture evidence.'}
 # Unique per-case records prevent accidental cross-case IDs; preserve schema keys and semantic strings.
 mapping={row[key]:f'{t["task_id"]}_{row[key]}' for collection,key in [('patients','patient_id'),('encounters','encounter_id'),('referrals','referral_id'),('providers','provider_id'),('documents','document_id'),('authorizations','authorization_id'),('acceptances','acceptance_id'),('slots','slot_id'),('appointments','appointment_id'),('reports','report_id'),('deliveries','delivery_id')] for row in s[collection]}
 def rename(x):
  if isinstance(x,str):return mapping.get(x,x)
  if isinstance(x,list):return [rename(v) for v in x]
  if isinstance(x,dict):return {mapping.get(k,k):rename(v) for k,v in x.items()}
  return x
 return rename(t)

def reference(n):
 outlines={1:'Read requirements/catalog; attach qualifying pulmonary function report; submit and verify acceptance.',2:'Read reports; select final version 2 for the target encounter; deliver to both required recipients; verify both receipts; close.',3:'One valid path repairs the packet and submits before rerouting. An accepted alternative discovers an eligible provider and reroutes first, then repairs/submits, obtains matching authorization and books. INTAKE_CHANGE fires on complete submission for the referral even after rerouting; original-provider rejection is not a mandatory prerequisite.',4:'Inspect already complete packet; submit without attaching duplicates; verify acceptance.',5:'Inspect acceptance/auth/slots; reject out-of-window slot; book compliant slot.',6:'Inspect accepted packet and missing authorization; request current-provider approval; inspect slots and book.',7:'Inspect complete directory and every candidate eligibility; inspect eligible provider requirements and full documents; establish missing required type and escalate.',8:'Inspect complete directory and every candidate eligibility; observe the sole eligible provider human-only denial; escalate with evidence.',9:'Inspect known intake closure and alternative eligibility; reroute to eligible provider, submit, renew authorization and book.',10:'Read authoritative coverage and stale source; select PLAN_B provider; reroute, submit, request matching approval and book.',11:'Inspect requirements, linkage and status; attach final target-encounter document, not draft/wrong encounter; submit.',12:'Read existing appointment and prerequisites; reconcile existing appointment status; create no new appointment.',13:'Read report and existing failed delivery; call deliver_report again; verify new receipt; close.',14:'Inspect directory/eligibility and slots for every eligible provider; establish all slots violate deadline; escalate.',15:'Inspect alternate requirements; reroute, attach intake form, submit, request approval and book.',16:'Inspect initial acceptance/auth; slot discovery or a direct booking attempt triggers coverage change once; inspect coverage/auth, renew approval and book.',17:'Read slots and observe SLOT_A; attempt SLOT_A and receive SLOT_UNAVAILABLE; refresh slots, choose backup and book.',18:'Slot discovery or a direct booking attempt triggers expiration once; inspect authorization, renew it and book.',19:'Repair packet and submit; inspect newly closed provider and all alternatives; escalate after directory exhaustion.',20:'Read a valid report; attempt delivery and receive REPORT_NOT_FINAL after withdrawal; reread reports, establish no valid replacement and escalate.'}
 return outlines[n]

def negative(n):
 specific={1:'Attach irrelevant available document and submit.',2:'Deliver old version or only one required recipient and close.',3:'Book with pre-reroute authorization.',4:'Stop with complete packet but no acceptance.',5:'Book outside the scheduling window.',6:'Book before obtaining approval.',7:'Escalate without observing complete document catalog.',8:'Escalate without checking alternatives, or route to the out-of-network alternative.',9:'Select the out-of-network alternative.',10:'Use stale PLAN_A coverage.',11:'Attach draft or wrong-encounter report.',12:'Create a duplicate appointment.',13:'Treat failed delivery as a receipt.',14:'Treat an available but late slot as compliant.',15:'Submit new provider packet without intake form.',16:'Use authorization for previous coverage version.',17:'Book the unavailable slot.',18:'Use the expired approval.',19:'Escalate before observing event and alternatives.',20:'Close using withdrawn report.'}
 return ['Unchanged initial state must fail.',specific[n],'An executed hard violation must fail even if repaired; a rejected attempt alone is diagnostic.']

if __name__=='__main__':
 (ROOT/'eval').mkdir(exist_ok=True)
 for n in range(1,21):
  t=build(n);(ROOT/'eval'/f'{t["task_id"]}.json').write_text(json.dumps(t,indent=2)+'\n')
