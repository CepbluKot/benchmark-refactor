"""Run against the local Control API after the v2 strategy and options contract is live."""
import json
import urllib.error
import urllib.request
from uuid import uuid4

BASE = 'http://127.0.0.1:18900'


def request(path, body=None, method='GET'):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as response:
        return json.load(response)


config = {
    'schema_version': 2,
    'procedure': 'phased',
    'search_space': {
        'column_types': [{'by_type': 'String', 'alternatives': ['LowCardinality(String)']}],
        'codecs': [{'by_type': 'String', 'alternatives': ['ZSTD(3)']}],
        'skip_indexes': [],
        'order_by': {'candidates': []},
        'column_order': [],
        'table_index_granularity_values': [8192],
    },
    'budget': {'rows_per_insert': 100000, 'insert_repetitions': 3, 'max_candidates': 100, 'top_n': 10},
    'scoring': {'preset': 'balanced', 'formula': 'read_gain', 'direction': 'maximize'},
}
created = None
try:
    suggestions = request('/api/v1/strategy-options/suggest', {
        'schema_version': 1,
        'kind': 'codec_alternative',
        'locale': 'en',
        'query': 'zstd',
        'matcher': {'by_type': 'String'},
        'selected': ['ZSTD(1)'],
        'limit': 20,
    }, 'POST')
    assert suggestions['catalogue_revision']
    assert all(item['canonical_value'] != 'ZSTD(1)' for item in suggestions['items'])
    assert any(item['canonical_value'] == 'ZSTD(3)' for item in suggestions['items'])
    body = {'name': f'V2 strategy {uuid4()}', 'description': 'v2 API check', 'config': config}
    created = request('/api/v1/strategies', body, 'POST')['aggregate_id']
    persisted = next(item for item in request('/api/v1/bootstrap')['strategies'] if item['id'] == created)
    assert persisted['config'] == config
    assert persisted['phases'] == ['types', 'codecs', 'index_granularity', 'final_validation']
    try:
        request('/api/v1/strategies', {**body, 'config': {**config, 'search_space': {**config['search_space'], 'column_types': [{'by_type': 'String', 'alternatives': []}]}}}, 'POST')
        raise AssertionError('Invalid v2 strategy was accepted')
    except urllib.error.HTTPError as error:
        assert error.code == 422
    print('V2 strategy persistence and options contract passed')
finally:
    if created:
        request('/api/v1/strategies/' + created, {}, 'DELETE')
