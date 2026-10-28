"""Rebuild the four original synthetic development cases (never evaluation cases)."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).parent / 'dev'
COLLECTIONS = ['patients','encounters','referrals','providers','documents','authorizations','acceptances',
               'slots','appointments','reports','deliveries','escalations']

def base():
    state={k:[] for k in COLLECTIONS}
    state['patients']=[{'patient_id':'P1','insurance_plan_id':'PLAN_A','coverage_version':1}]
    state['encounters']=[{'encounter_id':'E1','patient_id':'P1','status':'planned'}]
    state['referrals']=[{'referral_id':'R1','patient_id':'P1','encounter_id':'E1','target_specialty':'Cardiology',
        'provider_id':'CARD_A','referring_clinician_id':'PCP1','status':'rejected','rejection_codes':['incomplete_packet'],
        'attached_document_ids':['ORDER1'],'requirements_version':1,'acceptance_id':None,
        'allowed_recipient_ids':['PCP1'],'scheduling_constraints':{'earliest':'2026-09-02T00:00:00Z','latest':'2026-09-20T00:00:00Z'}}]
    rules=[{'document_type':'referral_order','statuses':['signed'],'linkage':'referral'},
           {'document_type':'echocardiogram_report','statuses':['final'],'linkage':'encounter'}]
    state['providers']=[{'provider_id':p,'specialty':'Cardiology','accepted_plan_ids':['PLAN_A'],
        'accepting_referrals':True,'requirements_version':1,'required_document_rules':copy.deepcopy(rules),
        'authorization_required':True} for p in ('CARD_A','CARD_B')]
    state['documents']=[{'document_id':ident,'patient_id':'P1','encounter_id':'E1','related_referral_ids':['R1'],
        'document_type':kind,'status':status,'version':1,'created_at':'2026-08-31T09:00:00Z','available':True}
        for ident,kind,status in [('ORDER1','referral_order','signed'),('ECHO1','echocardiogram_report','final')]]
    state['authorizations']=[{'authorization_id':'AUTH1','referral_id':'R1','provider_id':'CARD_A',
        'insurance_plan_id':'PLAN_A','coverage_version':1,'status':'approved','valid_from':'2026-08-01T00:00:00Z',
        'valid_until':'2026-10-01T00:00:00Z','human_appeal_required':False,'decision_code':'approved'}]
    state['slots']=[{'slot_id':'SLOT_'+p[-1], 'provider_id':p,'start_at':'2026-09-10T10:00:00Z',
                     'end_at':'2026-09-10T10:30:00Z','available':True} for p in ('CARD_A','CARD_B')]
    return {'schema_version':'1.0','task_id':'DEV_001','metadata':{'split':'dev','provenance':'Original synthetic development case'},
        'agent_input':{'referral_id':'R1','goal':'Recover R1 so its cardiology provider accepts the referral.'},
        'public_policy':{'clinical_intent_fixed':True,'escalation':'Use evidence when an authorized action requires human intervention.'},
        'environment':{'clock_start':'2026-09-01T09:00:00Z','logical_call_duration_seconds':60,
            'initial_state':state,'events':[],'simulation':{'authorization_decisions':{},'delivery_outcomes':{}}},
        'evaluation':{'expected_status':'accepted','initial_blocker_codes':['missing_required_document'],'escalation_required':False}}

def cases():
    one=base()
    two=base(); two['task_id']='DEV_002'; two['agent_input']['goal']='Recover R1 and schedule with an eligible provider.'
    two['evaluation']['expected_status']='scheduled'
    two['environment']['events']=[{'event_id':'INTAKE_CLOSES','trigger':{'phase':'before','tool':'submit_referral','arguments_match':{'referral_id':'R1'},'packet_complete':True},
        'changes':[{'collection':'providers','id':'CARD_A','set':{'accepting_referrals':False}}]}]
    three=base(); three['task_id']='DEV_003'; three['agent_input']['goal']='Return the correct report to PCP1 and close referral R1.'
    st=three['environment']['initial_state']; ref=st['referrals'][0]
    ref.update(status='completed',attached_document_ids=['ORDER1','ECHO1'],rejection_codes=[],acceptance_id='ACC0')
    st['encounters'][0]['status']='completed'
    st['acceptances']=[{'acceptance_id':'ACC0','referral_id':'R1','provider_id':'CARD_A','requirements_version':1,
        'packet_document_versions':{'ORDER1':1,'ECHO1':1},'active':True,'issued_at':'2026-08-20T09:00:00Z'}]
    st['slots'][0].update(start_at='2026-08-25T10:00:00Z',end_at='2026-08-25T10:30:00Z',available=False)
    st['appointments']=[{'appointment_id':'AP0','referral_id':'R1','patient_id':'P1','provider_id':'CARD_A',
        'slot_id':'SLOT_A','status':'completed','booked_at':'2026-08-21T09:00:00Z','acceptance_id':'ACC0','authorization_id':'AUTH1'}]
    st['encounters'].append({'encounter_id':'E_OLD','patient_id':'P1','status':'completed'})
    st['reports']=[{'report_id':ident,'patient_id':'P1','encounter_id':enc,'referral_id':'R1','appointment_id':'AP0',
        'status':'final','version':1,'available':True,'supersedes_report_id':None} for ident,enc in [('REPORT_GOOD','E1'),('REPORT_OLD','E_OLD')]]
    three['evaluation']={'expected_status':'closed','initial_blocker_codes':['report_delivery_pending'],'escalation_required':False}
    four=base(); four['task_id']='DEV_004'; four['agent_input']['goal']='Recover R1 or document an evidence-based human handoff.'
    four['environment']['initial_state']['documents'][1]['available']=False
    four['evaluation']={'expected_status':'escalated','initial_blocker_codes':['required_document_unavailable'],'escalation_required':True}
    return [one,two,three,four]

if __name__=='__main__':
    ROOT.mkdir(exist_ok=True)
    for task in cases(): (ROOT/(task['task_id']+'.json')).write_text(json.dumps(task,indent=2)+'\n')
