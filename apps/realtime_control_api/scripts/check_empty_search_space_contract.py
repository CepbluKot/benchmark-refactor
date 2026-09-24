from copy import deepcopy

from pydantic import ValidationError

from realtime_control_api.main import StrategyTemplateConfigV2, strategy_projection


BASE_CONFIG = {
    'schema_version': 2,
    'procedure': 'combined',
    'search_space': {
        'column_types': [],
        'codecs': [],
        'skip_indexes': [],
        'order_by': {'candidates': []},
        'column_order': [],
        'table_index_granularity_values': [],
    },
    'budget': {
        'rows_per_insert': 100000,
        'insert_repetitions': 3,
        'max_candidates': 100,
        'top_n': 10,
    },
    'scoring': {
        'preset': 'balanced',
        'formula': 'read_gain',
        'direction': 'maximize',
    },
}


for procedure in ('combined', 'sequential', 'phased'):
    raw = deepcopy(BASE_CONFIG)
    raw['procedure'] = procedure
    config = StrategyTemplateConfigV2.model_validate(raw)
    _, phases = strategy_projection(config)
    assert phases == [], (procedure, phases)

invalid = deepcopy(BASE_CONFIG)
invalid['search_space']['column_types'] = [
    {'by_type': 'String', 'alternatives': []},
]
try:
    StrategyTemplateConfigV2.model_validate(invalid)
except ValidationError:
    pass
else:
    raise AssertionError('A present type rule without alternatives must remain invalid')

print('Empty strategy search-space model contract passed')
