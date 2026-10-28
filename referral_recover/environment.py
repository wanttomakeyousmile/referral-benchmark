"""Deterministic synthetic referral tools. Standard library only, Python >=3.10.

Environment is a trusted host object, NOT an agent sandbox. Expose only
AgentSession.context(), definitions(), call(), and memory to agent adapters.
"""
from __future__ import annotations
import copy
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .catalog import TOOLS, READS, MUTATIONS, BLOCKERS, HUMAN_ACTION_CODES, PREMATURE, tool_definitions

IDS = {'patients': 'patient_id', 'encounters': 'encounter_id', 'referrals': 'referral_id',
       'providers': 'provider_id', 'documents': 'document_id', 'authorizations': 'authorization_id',
       'acceptances': 'acceptance_id', 'slots': 'slot_id', 'appointments': 'appointment_id',
       'reports': 'report_id', 'deliveries': 'delivery_id', 'escalations': 'ticket_id'}
RECOVERABLE = {'pending', 'submitted', 'rejected', 'accepted'}
STATUSES = {'referrals': RECOVERABLE | {'scheduled', 'completed', 'closed', 'escalated'},
           'documents': {'draft', 'final', 'signed', 'withdrawn'},
           'authorizations': {'pending', 'approved', 'denied', 'invalidated', 'expired'},
           'reports': {'draft', 'final', 'withdrawn', 'superseded'},
           'appointments': {'scheduled', 'completed', 'cancelled'},
           'encounters': {'planned', 'completed'}, 'deliveries': {'pending', 'received', 'failed'}}
# Trusted scenario event patch vocabulary; agents cannot call event operations.
PATCHABLE = {'providers': {'accepting_referrals', 'accepted_plan_ids', 'requirements_version', 'required_document_rules'},
             'patients': {'insurance_plan_id', 'coverage_version'},
             'documents': {'available', 'status', 'version'},
             'reports': {'available', 'status', 'version'},
             'slots': {'available'}, 'authorizations': {'status', 'valid_until', 'decision_code'},
             'deliveries': {'status', 'failure_code'}}

def clone(x): return copy.deepcopy(x)
def stamp(x): return datetime.fromisoformat(x.replace('Z', '+00:00'))
def iso(x): return x.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
def encode(x): return json.dumps(x, sort_keys=True, allow_nan=False)


PRECONDITION_CODES = {
    'PACKET_INCOMPLETE': 'packet_complete', 'REFERRAL_NOT_ACCEPTED': 'acceptance_valid',
    'AUTHORIZATION_INVALID': 'authorization_valid', 'PROVIDER_INELIGIBLE': 'provider_eligible',
    'SLOT_UNAVAILABLE': 'slot_available', 'SLOT_CONSTRAINT_VIOLATION': 'slot_constraints',
    'DUPLICATE_APPOINTMENT': 'no_duplicate_appointment', 'REPORT_NOT_FINAL': 'current_report_matches',
    'REPORT_MISMATCH': 'current_report_matches', 'DOCUMENT_UNAVAILABLE': 'document_available',
    'DOCUMENT_MISMATCH': 'document_qualifies', 'RECIPIENT_NOT_ALLOWED': 'recipient_allowed',
    'APPOINTMENT_NOT_COMPLETED': 'appointment_completed', 'CLOSURE_REQUIREMENTS_UNMET': 'closure_valid',
    'HUMAN_APPEAL_REQUIRED': 'administrative_authorization_permitted',
    'APPOINTMENT_INVALID': 'appointment_valid', 'APPOINTMENT_MISMATCH': 'appointment_matches',
    'ACTIVE_APPOINTMENT_EXISTS': 'no_active_appointment', 'SLOT_MISMATCH': 'slot_matches',
    'INVALID_REFERRAL_STATE': 'referral_state_allows_operation',
    'INVALID_EVIDENCE_REFERENCE': 'evidence_references_valid',
}

def record_changes(before, after):
    return [{'collection': table, 'id': ident, 'before': clone(before[table].get(ident)),
             'after': clone(after[table].get(ident))}
            for table in IDS for ident in sorted(set(before[table]) | set(after[table]))
            if before[table].get(ident) != after[table].get(ident)]

class TaskError(ValueError): pass
class CallConflict(ValueError): pass
class BudgetExceeded(RuntimeError): pass
class StaleSession(RuntimeError): pass
class DomainError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code.replace('_', ' ').capitalize())

def validate_task(task):
    """Validate this release's data contract before creating or resetting a DB."""
    def require(ok, msg):
        if not ok: raise TaskError(msg)
    require(task.get('schema_version') == '1.0', 'schema_version must be 1.0')
    require(isinstance(task.get('task_id'), str) and task['task_id'], 'task_id required')
    require(isinstance(task.get('agent_input'), dict), 'agent_input required')
    require(set(task['agent_input']) == {'referral_id', 'goal'}, 'agent_input needs exactly referral_id and goal')
    require(all(isinstance(v, str) and v for v in task['agent_input'].values()), 'agent_input values must be strings')
    env = task.get('environment', {})
    raw = env.get('initial_state', {})
    require(set(raw) == set(IDS), 'initial_state must include all canonical collections (empty lists allowed)')
    state = {}
    for table, key in IDS.items():
        require(isinstance(raw[table], list), f'{table} must be a list')
        state[table] = {}
        for record in raw[table]:
            require(isinstance(record, dict), f'{table} records must be objects')
            ident = record.get(key)
            require(isinstance(ident, str) and bool(ident), f'{table}.{key} required')
            require(ident not in state[table], f'Duplicate ID {ident}')
            if table in STATUSES: require(record.get('status') in STATUSES[table], f'Invalid {table} status')
            for k in ('available', 'active', 'accepting_referrals', 'human_appeal_required'):
                if k in record: require(type(record[k]) is bool, f'{table}.{k} must be boolean')
            state[table][ident] = clone(record)
    require(len(state['referrals']) == 1, 'This release supports one target referral per trial')
    ref = state['referrals'].get(task['agent_input']['referral_id'])
    require(ref is not None, 'Target referral absent')
    links = {'patient_id': 'patients', 'encounter_id': 'encounters', 'provider_id': 'providers',
             'referral_id': 'referrals', 'appointment_id': 'appointments', 'slot_id': 'slots',
             'acceptance_id': 'acceptances', 'authorization_id': 'authorizations', 'report_id': 'reports',
             'supersedes_report_id': 'reports'}
    for table, rows in state.items():
        for row in rows.values():
            for field, target in links.items():
                if field != IDS[table] and row.get(field) is not None:
                    require(row[field] in state[target], f'Dangling {table}.{field}: {row[field]}')
    for field in ('patient_id', 'encounter_id', 'provider_id', 'target_specialty', 'referring_clinician_id',
                  'status', 'rejection_codes', 'attached_document_ids', 'requirements_version', 'acceptance_id',
                  'allowed_recipient_ids', 'scheduling_constraints'):
        require(field in ref, f'Missing referral field: {field}')
    require(isinstance(ref['allowed_recipient_ids'],list) and bool(ref['allowed_recipient_ids']) and all(isinstance(x,str) and x for x in ref['allowed_recipient_ids']), 'Nonempty allowed_recipient_ids required')
    require(set(ref['scheduling_constraints']) <= {'earliest','latest','allowed_slot_ids'}, 'Unsupported scheduling constraint')
    for k in ('earliest','latest'):
        if k in ref['scheduling_constraints']: stamp(ref['scheduling_constraints'][k])
    require(state['encounters'][ref['encounter_id']]['patient_id'] == ref['patient_id'], 'Target encounter patient mismatch')
    for docid in ref['attached_document_ids']: require(docid in state['documents'], 'Missing attached document')
    for patient in state['patients'].values():
        require('insurance_plan_id' in patient and 'coverage_version' in patient, 'Patient coverage required')
    for provider in state['providers'].values():
        for field in ('specialty', 'accepted_plan_ids', 'accepting_referrals', 'requirements_version',
                      'required_document_rules', 'authorization_required'):
            require(field in provider, f'Missing provider field: {field}')
        require(type(provider['authorization_required']) is bool, 'authorization_required must be bool')
        for rule in provider['required_document_rules']:
            require(set(rule) == {'document_type', 'statuses', 'linkage'}, 'Bad document requirement')
            require(rule['linkage'] in {'patient', 'encounter', 'referral'}, 'Unsupported linkage rule')
    for doc in state['documents'].values():
        require(all(k in doc for k in ('document_type', 'available', 'version', 'related_referral_ids')), 'Incomplete document')
        require(all(r in state['referrals'] for r in doc['related_referral_ids']), 'Bad related_referral_ids')
    for row in state['slots'].values():
        require(stamp(row['start_at']) < stamp(row['end_at']), 'Slot end must follow start')
    for row in state['authorizations'].values():
        require(all(k in row for k in ('insurance_plan_id', 'coverage_version', 'valid_from', 'valid_until',
                                      'human_appeal_required', 'decision_code')), 'Incomplete authorization')
        if row['status'] == 'approved': require(stamp(row['valid_from']) < stamp(row['valid_until']), 'Bad authorization dates')
    required_fields = {
        'encounters': {'patient_id','status'},
        'slots': {'provider_id','start_at','end_at','available'},
        'acceptances': {'referral_id','provider_id','requirements_version','packet_document_versions','active','issued_at'},
        'appointments': {'referral_id','patient_id','provider_id','slot_id','status','booked_at','acceptance_id','authorization_id'},
        'reports': {'patient_id','encounter_id','referral_id','appointment_id','status','version','available','supersedes_report_id'},
        'deliveries': {'referral_id','report_id','report_version','recipient_id','status','receipt_id','failure_code'},
        'escalations': {'referral_id','blocker_code','evidence_event_ids','attempted_action_event_ids','reason_unable_to_proceed','human_action_code','required_human_action','created_at'}
    }
    for table, fields in required_fields.items():
        for row in state[table].values():
            require(fields <= set(row), f'Incomplete {table} record')
            for key in ('issued_at','booked_at','created_at'):
                if key in row: stamp(row[key])
    for receipt in state['acceptances'].values():
        require(all(i in state['documents'] for i in receipt['packet_document_versions']), 'Acceptance refers to missing document')
    try:
        start = stamp(env['clock_start'])
        require(start.utcoffset() == timedelta(0), 'clock_start must use UTC')
    except (KeyError, TypeError, ValueError) as ex: raise TaskError('Invalid UTC clock_start') from ex
    require(type(env.get('logical_call_duration_seconds', 60)) is int and env.get('logical_call_duration_seconds', 60) > 0, 'Positive call duration required')
    sim = env.get('simulation', {})
    require(set(sim) <= {'authorization_decisions', 'delivery_outcomes'}, 'Unknown simulation settings')
    for provider, decision in sim.get('authorization_decisions', {}).items():
        require(provider in state['providers'] and decision in {'approved', 'denied', 'pending'}, 'Bad authorization decision')
    for recipient, outcome in sim.get('delivery_outcomes', {}).items():
        require(recipient in ref['allowed_recipient_ids'] and outcome in {'received', 'failed', 'pending'}, 'Bad delivery outcome')
    events = env.get('events', [])
    seen = set()
    for event in events:
        require(event.get('event_id') and event['event_id'] not in seen, 'Event ID missing or duplicate')
        seen.add(event['event_id'])
        alternatives = event.get('alternative_triggers', [])
        require(isinstance(alternatives, list), 'Bad alternative triggers')
        for trigger in [event.get('trigger', {})] + alternatives:
            require(isinstance(trigger, dict), 'Bad trigger')
            require(trigger.get('phase') in {'time', 'before', 'after'}, 'Bad event phase')
            if trigger['phase'] == 'time': stamp(trigger['at'])
            else:
                require(trigger.get('tool') in TOOLS, 'Unknown event tool')
                require(set(trigger.get('arguments_match', {})) <= set(TOOLS[trigger['tool']]), 'Bad event arguments')
        for change in event.get('changes', []):
            table = change.get('collection')
            require(table in PATCHABLE and change.get('id') in state[table], 'Bad event target')
            require(bool(change.get('set')) and set(change['set']) <= PATCHABLE[table], 'Bad event fields')
            for key, value in change['set'].items():
                if key == 'status': require(value in STATUSES[table], 'Bad event status')
                if key in {'available', 'accepting_referrals'}: require(type(value) is bool, 'Bad event boolean')
                if key in {'version','requirements_version','coverage_version'}: require(type(value) is int and value>0, 'Bad event version')
                if key == 'valid_until': stamp(value)
    # Pending simulation outcomes must explicitly declare resolution or a human-only policy.
    if 'pending' in sim.get('authorization_decisions', {}).values() or 'pending' in sim.get('delivery_outcomes', {}).values():
        require(bool(task.get('public_policy', {}).get('pending_requires_human')), 'Pending outcomes require public pending_requires_human in this release')
    ev = task.get('evaluation', {})
    require(set(ev.get('initial_blocker_codes', [])) <= set(BLOCKERS), 'Unknown initial blocker code')
    if 'escalation' in ev:
        require(ev['escalation'].get('barrier_code') in BLOCKERS, 'Unknown escalation barrier code')
        require(bool(ev['escalation'].get('allowed_human_action_codes')) and set(ev['escalation']['allowed_human_action_codes']) <= set(HUMAN_ACTION_CODES), 'Unknown human action code')
    for row in state['escalations'].values():
        require(row['blocker_code'] in BLOCKERS and row['human_action_code'] in HUMAN_ACTION_CODES, 'Invalid escalation code')
    return state

class Environment:
    """Host-only manager. Open existing stores with Environment(path)."""
    def __init__(self, db_path):
        self.path = str(db_path)
        if not Path(self.path).is_file(): raise FileNotFoundError(self.path)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA application_id').fetchone()[0] != 0x52524631:
            self.db.close(); raise ValueError('Not a referral recovery benchmark database')

    @classmethod
    def create(cls, task, db_path, *, max_tool_calls=30):
        state = validate_task(task)
        if type(max_tool_calls) is not int or max_tool_calls <= 0: raise ValueError('max_tool_calls must be positive')
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: never silently overwrite a previous run or unrelated database.
        with path.open('xb'): pass
        conn = sqlite3.connect(path)
        try:
            conn.executescript('''PRAGMA application_id=1381123633;
                CREATE TABLE runtime (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                CREATE TABLE calls (call_id TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE action_log (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL);''')
            conn.execute('INSERT INTO runtime VALUES (1, ?)', (encode(cls._fresh(task, state, max_tool_calls)),))
            conn.commit()
        finally: conn.close()
        return cls(path)

    @staticmethod
    def _fresh(task, state, budget):
        return {'task': clone(task), 'state': state, 'run_id': uuid.uuid4().hex,
                'time': task['environment']['clock_start'], 'counter': 0, 'sequence': 0,
                'version': 0, 'fired': [], 'tool_attempts': 0, 'max_tool_calls': budget}

    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def _load(self): return json.loads(self.db.execute('SELECT payload FROM runtime WHERE id=1').fetchone()[0])
    def _save(self, runtime): self.db.execute('UPDATE runtime SET payload=? WHERE id=1', (encode(runtime),))

    def reset(self, task=None):
        """Explicitly reset this trial store; invalidate old sessions. Other DBs untouched."""
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self._load()
            target = old['task'] if task is None else task
            state = validate_task(target)
            fresh = self._fresh(target, state, old['max_tool_calls'])
            self._save(fresh)
            self.db.execute('DELETE FROM calls')
            self.db.execute('DELETE FROM action_log')
        return AgentSession(self)

    def session(self): return AgentSession(self)
    def snapshot(self): return clone(self._load()['state'])
    def runtime_info(self):
        return {k: v for k, v in self._load().items() if k not in {'task', 'state'}}
    def logs(self): return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM action_log ORDER BY sequence')]
    def export(self, directory):
        dest = Path(directory); dest.mkdir(parents=True, exist_ok=True)
        (dest/'final_state.json').write_text(json.dumps(self.snapshot(), indent=2)+'\n')
        (dest/'actions.jsonl').write_text(''.join(encode(x)+'\n' for x in self.logs()))
        (dest/'runtime.json').write_text(json.dumps(self.runtime_info(), indent=2)+'\n')

    def dispatch(self, tool_name, arguments, *, call_id, run_id):
        if not isinstance(call_id, str) or not call_id: raise ValueError('call_id must be a nonempty string')
        request = encode({'tool_name': tool_name, 'arguments': arguments})
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            rt = self._load()
            if run_id != rt['run_id']: raise StaleSession('Trial reset; obtain a fresh session')
            cached = self.db.execute('SELECT request,response FROM calls WHERE call_id=?', (call_id,)).fetchone()
            if cached:
                if cached['request'] != request: raise CallConflict('call_id reused with different request')
                return json.loads(cached['response'])
            if rt['tool_attempts'] >= rt['max_tool_calls']: raise BudgetExceeded('Logical tool budget exhausted')
            rt['tool_attempts'] += 1
            before_all = clone(rt['state']); time_before = rt['time']; version_before = rt['version']
            rt['time'] = iso(stamp(rt['time']) + timedelta(seconds=rt['task']['environment'].get('logical_call_duration_seconds', 60)))
            error = self._arguments(tool_name, arguments)
            engine = Engine(rt, self.logs())
            event_logs = engine.events('time', tool_name, arguments)
            if not error: event_logs += engine.events('before', tool_name, arguments)
            engine.maintain()
            pre_operation = clone(rt['state'])
            before_counter = rt['counter']
            result = None
            if not error:
                try: result = engine.execute(tool_name, arguments)
                except DomainError as ex:
                    error = ex; rt['state'] = clone(pre_operation); rt['counter'] = before_counter
            operation_state = clone(rt['state'])
            if not error: event_logs += engine.events('after', tool_name, arguments)
            engine.maintain()
            if not error:
                result = engine.read(tool_name, arguments) if tool_name in READS else engine.materialize(result)
            changed = rt['state'] != before_all
            rt['version'] += int(changed)
            rt['sequence'] += 1
            eid = f"EV_{rt['sequence']:04d}"
            response = {'call_id': call_id, 'ok': error is None, 'data': result if not error else None,
                        'error': {'code': error.code, 'message': str(error), 'retryable': False} if error else None,
                        'observation_event_id': eid, 'simulated_time': rt['time']}
            log = {'event_id': eid, 'run_id': run_id, 'sequence': rt['sequence'], 'call_id': call_id,
                   'tool_name': tool_name, 'arguments': clone(arguments), 'ok': error is None,
                   'error_code': error.code if error else None, 'premature': bool(error and error.code in PREMATURE),
                   'simulated_time_before': time_before, 'simulated_time_after': rt['time'],
                   'state_version_before': version_before, 'state_version_after': rt['version'],
                   'state_before': before_all, 'state_before_operation': pre_operation,
                   'state_after_operation': operation_state, 'state_after': clone(rt['state']),
                   'environment_events': event_logs, 'operation_changed': operation_state != pre_operation,
                   'response': response,
                   'log_schema_version': '1.1',
                   'failed_preconditions': [PRECONDITION_CODES[error.code]] if error and error.code in PRECONDITION_CODES else [],
                   'operation_changes': record_changes(pre_operation, operation_state),
                   'environment_event_ids': [e['event_id'] for e in event_logs]}
            self.db.execute('INSERT INTO action_log VALUES (?,?)', (rt['sequence'], encode(log)))
            self.db.execute('INSERT INTO calls VALUES (?,?,?)', (call_id, request, encode(response)))
            self._save(rt)
            return clone(response)

    @staticmethod
    def _arguments(name, args):
        if not isinstance(name, str) or name not in TOOLS: return DomainError('UNKNOWN_TOOL')
        if not isinstance(args, dict) or set(args) != set(TOOLS[name]): return DomainError('INVALID_ARGUMENTS')
        for k, v in args.items():
            if k.endswith('_event_ids'):
                if not isinstance(v, list) or any(not isinstance(x, str) or not x for x in v): return DomainError('INVALID_ARGUMENTS')
            elif not isinstance(v, str) or not v.strip(): return DomainError('INVALID_ARGUMENTS')
        if name == 'escalate' and args['blocker_code'] not in BLOCKERS: return DomainError('INVALID_ARGUMENTS')
        if name == 'escalate' and args['human_action_code'] not in HUMAN_ACTION_CODES: return DomainError('INVALID_ARGUMENTS')
        return None

class AgentSession:
    """Narrow adapter, not security isolation from arbitrary Python introspection."""
    def __init__(self, environment):
        self._environment = environment
        self._run_id = environment.runtime_info()['run_id']
        self.memory = {}
    def _current(self):
        rt = self._environment._load()
        if rt['run_id'] != self._run_id:
            self.memory.clear()
            raise StaleSession('Trial reset; obtain a fresh session')
        return rt
    def context(self):
        rt = self._current(); task = rt['task']
        return {'interface_version': '1.1', 'task_id': task['task_id'], **clone(task['agent_input']),
                'public_policy': clone(task.get('public_policy', {})), 'blocker_codes': list(BLOCKERS), 'human_action_codes': list(HUMAN_ACTION_CODES)}
    def definitions(self): self._current(); return tool_definitions()
    def call(self, name, arguments, *, call_id=None):
        self._current()
        return self._environment.dispatch(name, arguments, call_id=call_id or uuid.uuid4().hex, run_id=self._run_id)

class Engine:
    def __init__(self, runtime, logs): self.rt, self.logs = runtime, logs
    @property
    def state(self): return self.rt['state']
    def rows(self, table): return sorted(self.state[table].values(), key=lambda x: x[IDS[table]])
    def record(self, table, ident):
        if ident not in self.state[table]: raise DomainError('REFERRAL_NOT_FOUND' if table == 'referrals' else 'RECORD_NOT_FOUND')
        return self.state[table][ident]
    def ref(self, rid):
        if rid != self.rt['task']['agent_input']['referral_id']: raise DomainError('RECORD_OUT_OF_SCOPE')
        return self.record('referrals', rid)
    def linked(self, table, ref): return [x for x in self.rows(table) if x.get('referral_id') == ref['referral_id']]
    def new(self, table, values):
        while True:
            self.rt['counter'] += 1
            ident = f"{table.upper()}_{self.rt['counter']:04d}"
            if ident not in self.state[table]: break
        row = {IDS[table]: ident, **values}; self.state[table][ident] = row
        return row
    def public_ref(self, ref):
        out = clone(ref)
        out['appointment_ids'] = [x['appointment_id'] for x in self.linked('appointments', ref)]
        out['delivery_ids'] = [x['delivery_id'] for x in self.linked('deliveries', ref)]
        out['escalation_ids'] = [x['ticket_id'] for x in self.linked('escalations', ref)]
        out['acceptance_valid'] = self.accepted(ref)
        return out
    def eligible(self, ref, provider):
        patient = self.record('patients', ref['patient_id'])
        checks = {'specialty_match': provider['specialty'] == ref['target_specialty'],
                  'network_match': patient['insurance_plan_id'] in provider['accepted_plan_ids'],
                  'accepting_referrals': provider['accepting_referrals']}
        return {**checks, 'eligible': all(checks.values()), 'provider_id': provider['provider_id'],
                'reason_codes': [k for k,v in checks.items() if not v]}
    def qualifies(self, ref, doc, rule):
        return (doc['available'] and doc['patient_id'] == ref['patient_id'] and
                doc['document_type'] == rule['document_type'] and doc['status'] in rule['statuses'] and
                (rule['linkage'] != 'encounter' or doc['encounter_id'] == ref['encounter_id']) and
                (rule['linkage'] != 'referral' or ref['referral_id'] in doc['related_referral_ids']))
    def packet(self, ref):
        provider = self.record('providers', ref['provider_id'])
        docs = [self.record('documents', i) for i in ref['attached_document_ids']]
        return all(any(self.qualifies(ref, d, rule) for d in docs) for rule in provider['required_document_rules'])
    def versions(self, ref):
        return {i: self.record('documents', i)['version'] for i in ref['attached_document_ids']}
    def accepted(self, ref):
        ac = self.state['acceptances'].get(ref['acceptance_id'])
        p = self.record('providers', ref['provider_id'])
        return bool(ac and ac['active'] and ac['referral_id'] == ref['referral_id'] and
                    ac['provider_id'] == ref['provider_id'] and ac['requirements_version'] == p['requirements_version'] and
                    ac['packet_document_versions'] == self.versions(ref) and self.packet(ref))
    def valid_auth(self, ref, row, at=None):
        patient = self.record('patients', ref['patient_id'])
        now = stamp(self.rt['time'])
        return (row['referral_id'] == ref['referral_id'] and row['provider_id'] == ref['provider_id'] and
                row['insurance_plan_id'] == patient['insurance_plan_id'] and row['coverage_version'] == patient['coverage_version'] and
                row['status'] == 'approved' and stamp(row['valid_from']) <= now < stamp(row['valid_until']) and
                (at is None or stamp(row['valid_from']) <= stamp(at) < stamp(row['valid_until'])))
    def active_auth(self, ref, at=None):
        return next((a for a in self.linked('authorizations', ref) if self.valid_auth(ref, a, at)), None)
    def maintain(self):
        for ref in self.rows('referrals'):
            patient = self.record('patients', ref['patient_id'])
            for auth in self.linked('authorizations', ref):
                if auth['status'] in {'approved', 'pending'}:
                    if (auth['provider_id'] != ref['provider_id'] or auth['insurance_plan_id'] != patient['insurance_plan_id'] or auth['coverage_version'] != patient['coverage_version']): auth['status'] = 'invalidated'
                    elif auth['status'] == 'approved' and stamp(auth['valid_until']) <= stamp(self.rt['time']): auth['status'] = 'expired'
            ac = self.state['acceptances'].get(ref['acceptance_id'])
            if ac and not self.accepted(ref):
                ac['active'] = False
                if ref['status'] == 'accepted': ref['status'] = 'pending'
    def events(self, phase, name, args):
        fired = []
        for event in self.rt['task']['environment'].get('events', []):
            if event['event_id'] in self.rt['fired']: continue
            match = False
            for t in [event['trigger']] + event.get('alternative_triggers', []):
                if t['phase'] != phase: continue
                if phase == 'time': candidate = stamp(t['at']) <= stamp(self.rt['time'])
                else:
                    candidate = t['tool'] == name and isinstance(args, dict) and all(args.get(k) == v for k,v in t.get('arguments_match', {}).items())
                    if candidate and t.get('packet_complete'):
                        try: candidate = self.packet(self.ref(args['referral_id']))
                        except DomainError: candidate = False
                if candidate:
                    match = True
                    break
            if not match: continue
            changes = []
            for ch in event['changes']:
                row = self.record(ch['collection'], ch['id']); before = clone(row)
                row.update(clone(ch['set']))
                if ch['collection'] == 'deliveries' and row['status'] == 'received' and not row['receipt_id']:
                    row['receipt_id'] = f"RECEIPT_{event['event_id']}"
                changes.append({'collection': ch['collection'], 'id': ch['id'], 'before': before, 'after': clone(row)})
            self.rt['fired'].append(event['event_id'])
            fired.append({'event_id': event['event_id'], 'phase': phase, 'changes': changes})
        return fired
    def read(self, name, a):
        if name == 'get_provider_requirements': return clone(self.record('providers', a['provider_id']))
        ref = self.ref(a['referral_id'])
        if name == 'get_referral': return self.public_ref(ref)
        if name == 'get_coverage':
            p = self.record('patients', ref['patient_id'])
            return {'authoritative': clone(p), 'source': 'payer_registry', 'other_sources': clone(p.get('coverage_sources', []))}
        if name == 'get_documents':
            return {'documents': [{**clone(x), 'attached': x['document_id'] in ref['attached_document_ids']} for x in self.rows('documents')]}
        if name == 'find_providers': return {'providers': [{'provider_id': p['provider_id'], 'specialty': p['specialty']} for p in self.rows('providers') if p['specialty'] == ref['target_specialty']]}
        if name == 'check_provider_eligibility': return self.eligible(ref, self.record('providers', a['provider_id']))
        if name == 'check_authorization':
            return {'required': self.record('providers', ref['provider_id'])['authorization_required'],
                    'authorizations': [{**clone(x), 'currently_valid': self.valid_auth(ref,x)} for x in self.linked('authorizations', ref)]}
        if name == 'find_appointment_slots':
            self.record('providers', a['provider_id'])
            return {'constraints': clone(ref['scheduling_constraints']), 'slots': [clone(x) for x in self.rows('slots') if x['provider_id'] == a['provider_id'] and x['available'] and stamp(x['start_at']) > stamp(self.rt['time'])]}
        if name == 'get_appointments': return {'appointments': clone(self.linked('appointments', ref))}
        if name == 'get_consultation_reports': return {'reports': clone(self.rows('reports'))}
        if name == 'get_report_delivery':
            d = self.record('deliveries', a['delivery_id'])
            if d['referral_id'] != ref['referral_id']: raise DomainError('RECORD_OUT_OF_SCOPE')
            return clone(d)
        raise DomainError('UNKNOWN_TOOL')
    def materialize(self, result):
        table, ident, changed = result
        row = self.record(table, ident)
        return {'changed': changed, 'record': self.public_ref(row) if table == 'referrals' else clone(row)}
    def result(self, table, record, changed=True): return (table, record[IDS[table]], changed)
    def ensure(self, condition, code):
        if not condition: raise DomainError(code)
    def current_report(self, ref, report):
        ap = self.state['appointments'].get(report['appointment_id'])
        return (report['patient_id'] == ref['patient_id'] and report['encounter_id'] == ref['encounter_id'] and
                report['referral_id'] == ref['referral_id'] and report['available'] and report['status'] == 'final' and
                ap is not None and ap['referral_id'] == ref['referral_id'] and ap['patient_id'] == ref['patient_id'] and ap['status'] == 'completed' and
                not any(x.get('supersedes_report_id') == report['report_id'] and x['status'] == 'final' for x in self.rows('reports')))
    def closure(self, ref):
        if self.record('encounters', ref['encounter_id'])['status'] != 'completed': return False
        for report in self.rows('reports'):
            if self.current_report(ref, report) and all(any(d['report_id'] == report['report_id'] and d['report_version'] == report['version'] and d['recipient_id'] == recipient and d['status'] == 'received' and d['receipt_id'] for d in self.linked('deliveries', ref)) for recipient in ref['allowed_recipient_ids']): return True
        return False
    def execute(self, name, a):
        if name in READS: return self.read(name, a)
        ref = self.ref(a['referral_id']); rid = ref['referral_id']
        if name == 'close_referral' and ref['status'] == 'closed':
            self.ensure(self.closure(ref), 'CLOSURE_REQUIREMENTS_UNMET')
            return self.result('referrals', ref, False)
        self.ensure(ref['status'] not in {'closed', 'escalated'}, 'INVALID_REFERRAL_STATE')
        p = self.record('providers', ref['provider_id'])
        if name in {'attach_document', 'submit_referral', 'reroute_referral', 'request_authorization', 'schedule_appointment'}:
            self.ensure(ref['status'] in RECOVERABLE or (name == 'schedule_appointment' and ref['status'] == 'scheduled'), 'INVALID_REFERRAL_STATE')
        if name == 'attach_document':
            d = self.record('documents', a['document_id'])
            self.ensure(d['available'], 'DOCUMENT_UNAVAILABLE')
            self.ensure(any(self.qualifies(ref,d,r) for r in p['required_document_rules']), 'DOCUMENT_MISMATCH')
            changed = d['document_id'] not in ref['attached_document_ids']
            if changed: ref['attached_document_ids'].append(d['document_id'])
            return self.result('referrals', ref, changed)
        if name == 'submit_referral':
            self.ensure(self.packet(ref), 'PACKET_INCOMPLETE')
            if p.get('submission_requires_authorization'):
                self.ensure(not p['authorization_required'] or self.active_auth(ref), 'AUTHORIZATION_INVALID')
            eligibility = self.eligible(ref,p)
            if not eligibility['eligible']:
                if ref['acceptance_id']: self.record('acceptances',ref['acceptance_id'])['active'] = False
                ref.update(status='rejected', rejection_codes=eligibility['reason_codes'])
                return self.result('referrals',ref)
            if self.accepted(ref): return self.result('referrals',ref,False)
            receipt = self.new('acceptances', {'referral_id':rid,'provider_id':p['provider_id'], 'requirements_version':p['requirements_version'],
                'packet_document_versions':self.versions(ref),'active':True,'issued_at':self.rt['time']})
            ref.update(status='accepted',rejection_codes=[],acceptance_id=receipt['acceptance_id'],requirements_version=p['requirements_version'])
            return self.result('referrals',ref)
        if name == 'reroute_referral':
            target = self.record('providers',a['provider_id'])
            self.ensure(self.eligible(ref,target)['eligible'],'PROVIDER_INELIGIBLE')
            self.ensure(not any(x['status']=='scheduled' for x in self.linked('appointments',ref)), 'ACTIVE_APPOINTMENT_EXISTS')
            if ref['provider_id']==a['provider_id']: return self.result('referrals',ref,False)
            if ref['acceptance_id']: self.record('acceptances',ref['acceptance_id'])['active']=False
            ref.update(provider_id=a['provider_id'],status='pending',rejection_codes=[],acceptance_id=None,requirements_version=target['requirements_version'])
            self.maintain()
            return self.result('referrals',ref)
        if name == 'request_authorization':
            self.ensure(self.eligible(ref,p)['eligible'],'PROVIDER_INELIGIBLE')
            self.ensure(self.packet(ref),'PACKET_INCOMPLETE')
            if not p['authorization_required']: return self.result('referrals',ref,False)
            active = self.active_auth(ref)
            if active: return self.result('authorizations',active,False)
            patient = self.record('patients',ref['patient_id'])
            history = [x for x in self.linked('authorizations',ref) if x['provider_id']==ref['provider_id'] and x['coverage_version']==patient['coverage_version'] and x['insurance_plan_id']==patient['insurance_plan_id']]
            self.ensure(not any(x['status']=='denied' and x['human_appeal_required'] for x in history),'HUMAN_APPEAL_REQUIRED')
            pending = next((x for x in history if x['status']=='pending'),None)
            if pending: return self.result('authorizations',pending,False)
            decision = self.rt['task']['environment'].get('simulation',{}).get('authorization_decisions',{}).get(p['provider_id'],'approved')
            row = self.new('authorizations',{'referral_id':rid,'provider_id':ref['provider_id'],'insurance_plan_id':patient['insurance_plan_id'],
                'coverage_version':patient['coverage_version'],'status':decision,'valid_from':self.rt['time'],
                'valid_until':iso(stamp(self.rt['time'])+timedelta(days=30)), 'human_appeal_required':decision=='denied',
                'decision_code':'human_appeal_required' if decision=='denied' else decision})
            return self.result('authorizations',row)
        if name == 'schedule_appointment':
            self.ensure(not any(x['status']=='scheduled' for x in self.linked('appointments',ref)),'DUPLICATE_APPOINTMENT')
            self.ensure(self.accepted(ref),'REFERRAL_NOT_ACCEPTED')
            self.ensure(self.eligible(ref,p)['eligible'],'PROVIDER_INELIGIBLE')
            slot = self.record('slots',a['slot_id'])
            self.ensure(slot['provider_id']==ref['provider_id'],'SLOT_MISMATCH')
            auth = self.active_auth(ref,slot['start_at'] if ref.get('authorization_valid_on_visit',False) else None)
            self.ensure(not p['authorization_required'] or auth,'AUTHORIZATION_INVALID')
            self.ensure(slot['available'] and stamp(slot['start_at'])>stamp(self.rt['time']),'SLOT_UNAVAILABLE')
            self.ensure(self.slot_ok(ref,slot),'SLOT_CONSTRAINT_VIOLATION')
            ap = self.new('appointments',{'referral_id':rid,'patient_id':ref['patient_id'],'provider_id':ref['provider_id'],
                'slot_id':slot['slot_id'],'status':'scheduled','booked_at':self.rt['time'], 'acceptance_id':ref['acceptance_id'],
                'authorization_id':auth['authorization_id'] if auth else None})
            slot['available']=False; ref['status']='scheduled'
            return self.result('appointments',ap)
        if name == 'reconcile_appointment':
            ap = self.record('appointments',a['appointment_id'])
            self.ensure(ap['referral_id']==rid and ap['patient_id']==ref['patient_id'] and ap['provider_id']==ref['provider_id'],'APPOINTMENT_MISMATCH')
            slot=self.record('slots',ap['slot_id'])
            self.ensure(ap['status']=='scheduled' and slot['provider_id']==ref['provider_id'] and not slot['available'] and stamp(slot['start_at'])>stamp(self.rt['time']) and self.eligible(ref,p)['eligible'] and self.slot_ok(ref,slot),'APPOINTMENT_INVALID')
            self.ensure(not p['authorization_required'] or self.active_auth(ref,slot['start_at'] if ref.get('authorization_valid_on_visit',False) else None),'APPOINTMENT_INVALID')
            self.ensure(len([x for x in self.linked('appointments',ref) if x['status']=='scheduled'])==1,'APPOINTMENT_INVALID')
            self.ensure(self.booking_evidence(ref,ap),'APPOINTMENT_INVALID')
            changed = ref['status']!='scheduled'; ref['status']='scheduled'
            return self.result('referrals',ref,changed)
        if name == 'deliver_report':
            self.ensure(ref['status']=='completed' and self.record('encounters',ref['encounter_id'])['status']=='completed','APPOINTMENT_NOT_COMPLETED')
            report=self.record('reports',a['report_id'])
            self.ensure(report['available'] and report['status']=='final','REPORT_NOT_FINAL')
            self.ensure(self.current_report(ref,report),'REPORT_MISMATCH')
            self.ensure(a['recipient_id'] in ref['allowed_recipient_ids'],'RECIPIENT_NOT_ALLOWED')
            existing=next((x for x in self.linked('deliveries',ref) if x['report_id']==report['report_id'] and x['report_version']==report['version'] and x['recipient_id']==a['recipient_id'] and x['status'] in {'received','pending'}),None)
            if existing: return self.result('deliveries',existing,False)
            outcome=self.rt['task']['environment'].get('simulation',{}).get('delivery_outcomes',{}).get(a['recipient_id'],'received')
            row=self.new('deliveries',{'referral_id':rid,'report_id':report['report_id'],'report_version':report['version'],
                'recipient_id':a['recipient_id'],'status':outcome,'receipt_id':None,'failure_code':'transport_rejected' if outcome=='failed' else None})
            if outcome=='received': row['receipt_id']='RECEIPT_'+row['delivery_id']
            return self.result('deliveries',row)
        if name == 'close_referral':
            self.ensure(ref['status']=='completed' and self.closure(ref),'CLOSURE_REQUIREMENTS_UNMET')
            ref['status']='closed'; return self.result('referrals',ref)
        if name == 'escalate':
            prior={x['event_id']:x for x in self.logs}
            self.ensure(all(i in prior for i in a['evidence_event_ids']+a['attempted_action_event_ids']),'INVALID_EVIDENCE_REFERENCE')
            self.ensure(all(prior[i]['tool_name'] in MUTATIONS for i in a['attempted_action_event_ids']),'INVALID_EVIDENCE_REFERENCE')
            row=self.new('escalations',{'referral_id':rid,**{k:clone(v) for k,v in a.items() if k!='referral_id'},'created_at':self.rt['time']})
            ref['status']='escalated'; return self.result('escalations',row)
        raise DomainError('UNKNOWN_TOOL')
    def slot_ok(self,ref,slot):
        c=ref['scheduling_constraints']; when=stamp(slot['start_at'])
        return (('earliest' not in c or when>=stamp(c['earliest'])) and ('latest' not in c or when<=stamp(c['latest'])) and
                ('allowed_slot_ids' not in c or slot['slot_id'] in c['allowed_slot_ids']))
    def booking_evidence(self,ref,ap):
        ac=self.state['acceptances'].get(ap.get('acceptance_id'))
        if stamp(ap['booked_at'])>stamp(self.rt['time']): return False
        if not ac or ac['referral_id']!=ref['referral_id'] or ac['provider_id']!=ref['provider_id'] or stamp(ac['issued_at'])>stamp(ap['booked_at']): return False
        p=self.record('providers',ref['provider_id'])
        if not p['authorization_required']: return True
        au=self.state['authorizations'].get(ap.get('authorization_id'))
        return bool(au and au['referral_id']==ref['referral_id'] and au['provider_id']==ref['provider_id'] and au['status']=='approved' and
                    stamp(au['valid_from'])<=stamp(ap['booked_at'])<stamp(au['valid_until']))
