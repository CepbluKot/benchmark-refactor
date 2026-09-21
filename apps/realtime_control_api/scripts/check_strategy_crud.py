"""Run against a disposable local Control API with real PostgreSQL."""
import json
import urllib.request
import urllib.error
from uuid import uuid4
import websocket

BASE = 'http://127.0.0.1:18900'
def request(path, body=None, method='GET'):
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, method=method, headers={'Content-Type': 'application/json'})) as response:
        return json.load(response)

snapshot = request('/api/v1/bootstrap')
socket = websocket.create_connection(f"ws://127.0.0.1:18900/api/v1/events?after={snapshot['event_watermark']}", timeout=5)
def check_event(ack, kind):
    while True:
        event = json.loads(socket.recv())
        if event['event_id'] == ack['accepted_event_id']:
            assert event['event_type'] == kind
            return event['payload']

identifier = None
try:
    config = {
        'schema_version': 1,
        'method': 'types_strategy',
        'rules': {'column_types': True, 'codecs': True},
        'budget': {
            'rows_per_insert': 100000,
            'insert_repetitions': 3,
            'max_candidates': 100,
            'top_n': 10,
        },
        'scoring': {'priority': 'balanced'},
    }
    body = {'name': f'CRUD validation {uuid4()}', 'description': 'API contract check', 'config': config}
    ack = request('/api/v1/strategies', body, 'POST')
    identifier = ack['aggregate_id']
    created = check_event(ack, 'strategy.created')
    assert created['name'] == body['name']
    assert created['config']['method'] == config['method']
    assert created['config']['budget'] == config['budget']
    assert created['phases'] == ['types', 'codecs']
    body['name'] += ' updated'
    ack = request('/api/v1/strategies/' + identifier, body, 'PUT')
    assert check_event(ack, 'strategy.updated')['name'] == body['name']
    persisted = next(s for s in request('/api/v1/bootstrap')['strategies'] if s['id'] == identifier)
    assert persisted['name'] == body['name']
    assert persisted['config'] == created['config']
    for invalid in (
        {**body, 'phases': ['caller-controlled']},
        {**body, 'config': {**config, 'budget': {**config['budget'], 'max_candidates': 0}}},
        {**body, 'config': {**config, 'budget': {**config['budget'], 'final_validation_index_alternatives': 2}}},
    ):
        try:
            request('/api/v1/strategies', invalid, 'POST')
            raise AssertionError('Invalid strategy was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 422
    ack = request('/api/v1/strategies/' + identifier, {}, 'DELETE')
    check_event(ack, 'strategy.deleted')
    assert all(s['id'] != identifier for s in request('/api/v1/bootstrap')['strategies'])
    identifier = None
    if snapshot['benchmarks']:
        try:
            request('/api/v1/strategies/' + snapshot['benchmarks'][0]['strategyId'], {}, 'DELETE')
            raise AssertionError('Referenced strategy deletion was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 409
    print('Strategy CRUD, durable events, persistence and deletion guard passed')
finally:
    if identifier:
        request('/api/v1/strategies/' + identifier, {}, 'DELETE')
    socket.close()
