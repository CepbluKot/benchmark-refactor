from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

import psycopg
import uvicorn
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    icon: Literal['target', 'analytics', 'data', 'experiment', 'operations'] = 'target'


StrategyMethod = Literal['types_strategy', 'indexes_strategy', 'combined_strategy', 'sequential_topn_strategy', 'sequential_phased_topn_strategy']


class StrategyRules(ApiModel):
    column_types: bool = False
    codecs: bool = False
    skip_indexes: bool = False
    table_index_granularity: bool = False
    order_by: bool = False
    column_order: bool = False


class StrategyBudget(ApiModel):
    rows_per_insert: int = Field(gt=0)
    insert_repetitions: int = Field(gt=0)
    max_candidates: int = Field(gt=0)
    top_n: int = Field(gt=0)
    baseline_rows: int | None = Field(default=None, gt=0)
    candidate_rows: int | None = Field(default=None, gt=0)
    per_phase_candidates: int | None = Field(default=None, gt=0)
    winners_per_parent: int | None = Field(default=None, gt=0)
    final_validation_candidates: int | None = Field(default=None, gt=0)
    final_validation_index_alternatives: int | None = Field(default=None, gt=0)


class StrategyScoring(ApiModel):
    priority: Literal['balanced', 'faster_reads', 'faster_inserts', 'better_compression']
    max_storage_growth_percent: float | None = Field(default=None, allow_inf_nan=False)
    max_insert_slowdown_percent: float | None = Field(default=None, allow_inf_nan=False)
    min_select_improvement_percent: float | None = Field(default=None, allow_inf_nan=False)


class StrategyTemplateConfig(ApiModel):
    schema_version: Literal[1]
    method: StrategyMethod
    rules: StrategyRules
    budget: StrategyBudget
    scoring: StrategyScoring

    @model_validator(mode='after')
    def validate_method_fields(self) -> 'StrategyTemplateConfig':
        allowed = {
            'types_strategy': {'column_types', 'codecs'},
            'indexes_strategy': {'skip_indexes'},
            'combined_strategy': {'column_types', 'codecs', 'skip_indexes'},
            'sequential_topn_strategy': {'column_types', 'codecs', 'skip_indexes'},
            'sequential_phased_topn_strategy': {'column_types', 'codecs', 'skip_indexes', 'table_index_granularity', 'order_by', 'column_order'},
        }[self.method]
        enabled = {name for name, value in self.rules.model_dump().items() if value}
        if enabled - allowed:
            raise ValueError('Rules contain fields unsupported by the selected method')
        if self.method != 'sequential_phased_topn_strategy' and self.budget.final_validation_index_alternatives is not None:
            raise ValueError('Final-validation index alternatives require phased Top-N')
        return self


class StrategyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=500)
    config: StrategyTemplateConfig

    @field_validator('name')
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Strategy name is required')
        return value


def derive_phases(method: StrategyMethod) -> list[str]:
    return {
        'types_strategy': ['types', 'codecs'],
        'indexes_strategy': ['indexes'],
        'combined_strategy': ['types', 'codecs', 'indexes'],
        'sequential_topn_strategy': ['types', 'codecs', 'top_n', 'indexes'],
        'sequential_phased_topn_strategy': ['order_by', 'types', 'codecs', 'index_granularity', 'indexes', 'final_validation'],
    }[method]


class BenchmarkCreate(ApiModel):
    workspace_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=120)
    source_id: str = Field(min_length=1, max_length=160)
    source_table: str = Field(min_length=3, max_length=320)
    sandbox_database: str = Field(min_length=1, max_length=160)
    strategy_id: str = Field(min_length=1, max_length=160)


class BenchmarkUpdate(BenchmarkCreate):
    pass


class SourceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    login: str = Field(min_length=1, max_length=80)
    secret_ref: str = Field(min_length=1, max_length=160)


class SourceUpdate(SourceCreate):
    pass


class RunCreate(ApiModel):
    benchmark_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=128)


class EventBus:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def publish(self, event: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_json(event)
            except RuntimeError:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def database_url() -> str:
    value = os.environ.get('CONTROL_DATABASE_URL', '').strip()
    if not value:
        raise RuntimeError('CONTROL_DATABASE_URL is required')
    return value


def connect() -> psycopg.Connection[Any]:
    return psycopg.connect(database_url(), autocommit=False)


def clickhouse_query(sql: str, *, sandbox: bool = False, write: bool = False) -> str:
    prefix = 'CLICKHOUSE_SANDBOX' if sandbox else 'CLICKHOUSE_SOURCE'
    host = os.environ[f'{prefix}_HOST']
    port = os.environ.get(f'{prefix}_PORT', '8123')
    user = os.environ[f'{prefix}_USER']
    password = os.environ.get(f'{prefix}_PASSWORD', '')
    parameters = {'query': sql, 'user': user}
    if password:
        parameters['password'] = password
    query = urllib.parse.urlencode(parameters)
    request = urllib.request.Request(f'http://{host}:{port}/?{query}', method='POST') if write else f'http://{host}:{port}/?{query}'
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode('utf-8')


def initialize() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute('''
          CREATE TABLE IF NOT EXISTS workspaces (id text primary key, name text not null, icon text not null default 'target', created_at timestamptz not null);
          ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS icon text NOT NULL DEFAULT 'target';
          CREATE TABLE IF NOT EXISTS sources (id text primary key, name text not null, host text not null, port integer not null, login text not null, secret_ref text not null, status text not null, checked_at timestamptz, created_at timestamptz not null);
          CREATE TABLE IF NOT EXISTS strategies (id text primary key, name text not null, strategy text not null, phases jsonb not null, description text not null default '', config jsonb, created_at timestamptz not null);
          ALTER TABLE strategies ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '';
          ALTER TABLE strategies ADD COLUMN IF NOT EXISTS config jsonb;
          CREATE TABLE IF NOT EXISTS benchmarks (id text primary key, workspace_id text not null references workspaces(id), name text not null, source_id text not null references sources(id), source_table text not null, sandbox_database text not null, strategy_id text not null references strategies(id), strategy_snapshot jsonb, created_at timestamptz not null);
          ALTER TABLE benchmarks ADD COLUMN IF NOT EXISTS strategy_snapshot jsonb;
          CREATE TABLE IF NOT EXISTS runs (id text primary key, benchmark_id text not null references benchmarks(id), status text not null, stage text not null, source_rows bigint, candidate_rows bigint, started_at timestamptz not null, finished_at timestamptz, failure_reason text);
          CREATE TABLE IF NOT EXISTS commands (idempotency_key text primary key, command_id text not null, aggregate_id text not null, accepted_event_id bigint not null);
          CREATE TABLE IF NOT EXISTS event_log (event_id bigserial primary key, aggregate_type text not null, aggregate_id text not null, aggregate_revision integer not null, event_type text not null, command_id text, occurred_at timestamptz not null, payload jsonb not null);
        ''')
        cur.execute('''
          UPDATE strategies SET config = jsonb_build_object(
            'schema_version', 1,
            'method', strategy,
            'rules', jsonb_build_object(
              'column_types', strategy IN ('types_strategy','combined_strategy','sequential_topn_strategy','sequential_phased_topn_strategy'),
              'codecs', strategy IN ('types_strategy','combined_strategy','sequential_topn_strategy','sequential_phased_topn_strategy'),
              'skip_indexes', strategy IN ('indexes_strategy','combined_strategy','sequential_topn_strategy','sequential_phased_topn_strategy'),
              'table_index_granularity', strategy = 'sequential_phased_topn_strategy',
              'order_by', strategy = 'sequential_phased_topn_strategy',
              'column_order', strategy = 'sequential_phased_topn_strategy'
            ),
            'budget', jsonb_build_object('rows_per_insert',100000,'insert_repetitions',3,'max_candidates',100,'top_n',10),
            'scoring', jsonb_build_object('priority','balanced')
          ) WHERE config IS NULL
        ''')
        cur.execute('ALTER TABLE strategies ALTER COLUMN config SET NOT NULL')
        cur.execute('UPDATE benchmarks b SET strategy_snapshot=s.config FROM strategies s WHERE b.strategy_id=s.id AND b.strategy_snapshot IS NULL')
        cur.execute('ALTER TABLE benchmarks ALTER COLUMN strategy_snapshot SET NOT NULL')
        conn.commit()


def record_event(conn: psycopg.Connection[Any], aggregate_type: str, aggregate_id: str, event_type: str, payload: dict[str, Any], command_id: str | None = None) -> dict[str, Any]:
    stamp = now()
    with conn.cursor() as cur:
        cur.execute('SELECT coalesce(max(aggregate_revision), 0) + 1 FROM event_log WHERE aggregate_type=%s AND aggregate_id=%s', (aggregate_type, aggregate_id))
        revision = cur.fetchone()[0]
        cur.execute('INSERT INTO event_log (aggregate_type, aggregate_id, aggregate_revision, event_type, command_id, occurred_at, payload) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING event_id', (aggregate_type, aggregate_id, revision, event_type, command_id, stamp, json.dumps(payload)))
        event_id = cur.fetchone()[0]
    return {'schema_version': 1, 'event_id': event_id, 'aggregate_type': aggregate_type, 'aggregate_id': aggregate_id, 'aggregate_revision': revision, 'event_type': event_type, 'occurred_at': stamp, 'command_id': command_id, 'payload': payload}


def rows(query: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query, values)
        names = [item.name for item in cur.description]
        return [dict(zip(names, item, strict=True)) for item in cur.fetchall()]


def bootstrap() -> dict[str, Any]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT coalesce(max(event_id), 0) FROM event_log')
        watermark = cur.fetchone()[0]
    return {'event_watermark': watermark, 'workspaces': rows('SELECT id,name,icon FROM workspaces ORDER BY created_at'), 'sources': rows('SELECT id,name,host,port,login,status,checked_at AS "checkedAt" FROM sources ORDER BY created_at'), 'strategies': rows('SELECT id,name,description,strategy,phases,config FROM strategies ORDER BY created_at'), 'benchmarks': rows('SELECT id,workspace_id AS "workspaceId",name,source_id AS "sourceId",source_table AS "sourceTable",sandbox_database AS "sandboxDatabase",strategy_id AS "strategyId",strategy_snapshot AS "strategySnapshot" FROM benchmarks ORDER BY created_at'), 'runs': rows('SELECT id,benchmark_id AS "benchmarkId",status,stage,source_rows AS "sourceRows",candidate_rows AS "candidateRows",started_at AS "startedAt",finished_at AS "finishedAt",failure_reason AS "failureReason" FROM runs ORDER BY started_at DESC')}


def create_app() -> FastAPI:
    bus = EventBus()
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize()
        yield
    app = FastAPI(title='Benchmark Studio Control API', version='1.0.0', lifespan=lifespan)
    allowed_origins = [origin.strip() for origin in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if origin.strip()]
    if allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False, allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Content-Type'])

    @app.get('/health/live', status_code=204)
    def live() -> Response: return Response(status_code=204)

    @app.get('/health/ready', status_code=204)
    def ready() -> Response:
        with connect() as conn, conn.cursor() as cur: cur.execute('SELECT 1')
        clickhouse_query('SELECT 1')
        return Response(status_code=204)

    @app.get('/api/v1/bootstrap')
    def get_bootstrap() -> dict[str, Any]: return bootstrap()

    @app.post('/api/v1/workspaces', status_code=202)
    async def create_workspace(payload: WorkspaceCreate) -> dict[str, Any]:
        workspace_id = f'workspace-{uuid4()}'
        command_id = str(uuid4())
        with connect() as conn:
            conn.execute('INSERT INTO workspaces (id,name,icon,created_at) VALUES (%s,%s,%s,%s)', (workspace_id, payload.name.strip(), payload.icon, now()))
            event = record_event(conn, 'workspace', workspace_id, 'workspace.created', {'id': workspace_id, 'name': payload.name.strip(), 'icon': payload.icon}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': workspace_id, 'accepted_event_id': event['event_id']}

    @app.post('/api/v1/sources', status_code=202)
    async def create_source(payload: SourceCreate) -> dict[str, Any]:
        source_id = f'source-{uuid4()}'
        command_id = str(uuid4())
        with connect() as conn:
            conn.execute('INSERT INTO sources VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', (source_id, payload.name.strip(), payload.host, payload.port, payload.login, payload.secret_ref, 'unchecked', None, now()))
            event = record_event(conn, 'source', source_id, 'source.created', {'id': source_id, 'name': payload.name.strip(), 'host': payload.host, 'port': payload.port, 'login': payload.login, 'status': 'unchecked'}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': source_id, 'accepted_event_id': event['event_id']}

    @app.put('/api/v1/sources/{source_id}', status_code=202)
    async def update_source(source_id: str, payload: SourceUpdate) -> dict[str, Any]:
        command_id = str(uuid4())
        with connect() as conn:
            result = conn.execute(
                'UPDATE sources SET name=%s,host=%s,port=%s,login=%s,secret_ref=%s,status=%s,checked_at=%s WHERE id=%s RETURNING id',
                (payload.name.strip(), payload.host, payload.port, payload.login, payload.secret_ref, 'unchecked', None, source_id),
            )
            if not result.fetchone():
                raise HTTPException(404, 'Source not found')
            event = record_event(conn, 'source', source_id, 'source.updated', {'id': source_id, 'name': payload.name.strip(), 'host': payload.host, 'port': payload.port, 'login': payload.login, 'status': 'unchecked'}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': source_id, 'accepted_event_id': event['event_id']}

    @app.delete('/api/v1/sources/{source_id}', status_code=202)
    async def delete_source(source_id: str) -> dict[str, Any]:
        command_id = str(uuid4())
        with connect() as conn:
            if not conn.execute('SELECT id FROM sources WHERE id=%s FOR UPDATE', (source_id,)).fetchone():
                raise HTTPException(404, 'Source not found')
            if conn.execute('SELECT id FROM benchmarks WHERE source_id=%s LIMIT 1', (source_id,)).fetchone():
                raise HTTPException(409, 'Source is used by benchmarks')
            conn.execute('DELETE FROM sources WHERE id=%s', (source_id,))
            event = record_event(conn, 'source', source_id, 'source.deleted', {'id': source_id}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': source_id, 'accepted_event_id': event['event_id']}

    @app.post('/api/v1/strategies', status_code=202)
    async def create_strategy(payload: StrategyCreate) -> dict[str, Any]:
        strategy_id = f'strategy-{uuid4()}'
        command_id = str(uuid4())
        phases = derive_phases(payload.config.method)
        config = payload.config.model_dump(exclude_none=True)
        with connect() as conn:
            conn.execute('INSERT INTO strategies (id,name,strategy,phases,description,config,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)', (strategy_id, payload.name.strip(), payload.config.method, json.dumps(phases), payload.description.strip(), json.dumps(config), now()))
            event = record_event(conn, 'strategy', strategy_id, 'strategy.created', {'id': strategy_id, 'name': payload.name.strip(), 'description': payload.description.strip(), 'strategy': payload.config.method, 'phases': phases, 'config': config}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': strategy_id, 'accepted_event_id': event['event_id']}

    @app.put('/api/v1/strategies/{strategy_id}', status_code=202)
    async def update_strategy(strategy_id: str, payload: StrategyCreate) -> dict[str, Any]:
        if not payload.name.strip():
            raise HTTPException(422, 'Strategy name is required')
        command_id = str(uuid4())
        phases = derive_phases(payload.config.method)
        config = payload.config.model_dump(exclude_none=True)
        with connect() as conn:
            result = conn.execute('UPDATE strategies SET name=%s,description=%s,strategy=%s,phases=%s,config=%s WHERE id=%s RETURNING id', (payload.name.strip(), payload.description.strip(), payload.config.method, json.dumps(phases), json.dumps(config), strategy_id))
            if not result.fetchone():
                raise HTTPException(404, 'Strategy not found')
            event = record_event(conn, 'strategy', strategy_id, 'strategy.updated', {'id': strategy_id, 'name': payload.name.strip(), 'description': payload.description.strip(), 'strategy': payload.config.method, 'phases': phases, 'config': config}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': strategy_id, 'accepted_event_id': event['event_id']}

    @app.delete('/api/v1/strategies/{strategy_id}', status_code=202)
    async def delete_strategy(strategy_id: str) -> dict[str, Any]:
        command_id = str(uuid4())
        with connect() as conn:
            if not conn.execute('SELECT id FROM strategies WHERE id=%s FOR UPDATE', (strategy_id,)).fetchone():
                raise HTTPException(404, 'Strategy not found')
            if conn.execute('SELECT id FROM benchmarks WHERE strategy_id=%s LIMIT 1', (strategy_id,)).fetchone():
                raise HTTPException(409, 'Strategy is used by benchmarks')
            conn.execute('DELETE FROM strategies WHERE id=%s', (strategy_id,))
            event = record_event(conn, 'strategy', strategy_id, 'strategy.deleted', {'id': strategy_id}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': strategy_id, 'accepted_event_id': event['event_id']}

    @app.post('/api/v1/benchmarks', status_code=202)
    async def create_benchmark(payload: BenchmarkCreate) -> dict[str, Any]:
        benchmark_id = f'benchmark-{uuid4()}'
        command_id = str(uuid4())
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT 1 FROM workspaces WHERE id=%s', (payload.workspace_id,))
            if not cur.fetchone(): raise HTTPException(404, 'Workspace not found')
            cur.execute('SELECT 1 FROM sources WHERE id=%s', (payload.source_id,))
            if not cur.fetchone(): raise HTTPException(404, 'Source not found')
            cur.execute('SELECT config FROM strategies WHERE id=%s', (payload.strategy_id,))
            strategy_row = cur.fetchone()
            if not strategy_row: raise HTTPException(404, 'Strategy not found')
            strategy_snapshot = strategy_row[0]
            cur.execute('INSERT INTO benchmarks (id,workspace_id,name,source_id,source_table,sandbox_database,strategy_id,strategy_snapshot,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', (benchmark_id, payload.workspace_id, payload.name.strip(), payload.source_id, payload.source_table, payload.sandbox_database, payload.strategy_id, json.dumps(strategy_snapshot), now()))
            event = record_event(conn, 'benchmark', benchmark_id, 'benchmark.created', {'id': benchmark_id, 'workspaceId': payload.workspace_id, 'name': payload.name.strip(), 'sourceId': payload.source_id, 'sourceTable': payload.source_table, 'sandboxDatabase': payload.sandbox_database, 'strategyId': payload.strategy_id, 'strategySnapshot': strategy_snapshot}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': benchmark_id, 'accepted_event_id': event['event_id']}

    @app.put('/api/v1/benchmarks/{benchmark_id}', status_code=202)
    async def update_benchmark(benchmark_id: str, payload: BenchmarkUpdate) -> dict[str, Any]:
        command_id = str(uuid4())
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT 1 FROM benchmarks WHERE id=%s', (benchmark_id,))
            if not cur.fetchone(): raise HTTPException(404, 'Benchmark not found')
            cur.execute('SELECT 1 FROM workspaces WHERE id=%s', (payload.workspace_id,))
            if not cur.fetchone(): raise HTTPException(404, 'Workspace not found')
            cur.execute('SELECT 1 FROM sources WHERE id=%s', (payload.source_id,))
            if not cur.fetchone(): raise HTTPException(404, 'Source not found')
            cur.execute('SELECT config FROM strategies WHERE id=%s', (payload.strategy_id,))
            strategy_row = cur.fetchone()
            if not strategy_row: raise HTTPException(404, 'Strategy not found')
            strategy_snapshot = strategy_row[0]
            cur.execute('UPDATE benchmarks SET workspace_id=%s,name=%s,source_id=%s,source_table=%s,sandbox_database=%s,strategy_id=%s,strategy_snapshot=%s WHERE id=%s', (payload.workspace_id, payload.name.strip(), payload.source_id, payload.source_table, payload.sandbox_database, payload.strategy_id, json.dumps(strategy_snapshot), benchmark_id))
            event = record_event(conn, 'benchmark', benchmark_id, 'benchmark.updated', {'id': benchmark_id, 'workspaceId': payload.workspace_id, 'name': payload.name.strip(), 'sourceId': payload.source_id, 'sourceTable': payload.source_table, 'sandboxDatabase': payload.sandbox_database, 'strategyId': payload.strategy_id, 'strategySnapshot': strategy_snapshot}, command_id)
            conn.commit()
        await bus.publish(event)
        return {'command_id': command_id, 'aggregate_id': benchmark_id, 'accepted_event_id': event['event_id']}

    @app.get('/api/v1/sources/{source_id}/tables')
    def source_tables(source_id: str) -> dict[str, list[str]]:
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT 1 FROM sources WHERE id=%s', (source_id,))
            if not cur.fetchone(): raise HTTPException(404, 'Source not found')
        result = clickhouse_query("SELECT concat(database, '.', name) FROM system.tables WHERE database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA') ORDER BY database, name")
        return {'tables': [line for line in result.splitlines() if line]}

    @app.websocket('/api/v1/events')
    async def events(socket: WebSocket, after: int = 0) -> None:
        await socket.accept()
        for event in rows('SELECT event_id,aggregate_type,aggregate_id,aggregate_revision,event_type,occurred_at,command_id,payload FROM event_log WHERE event_id > %s ORDER BY event_id', (after,)):
            event['schema_version'] = 1
            await socket.send_json(jsonable_encoder(event))
        bus.clients.add(socket)
        try:
            while True: await socket.receive_text()
        except WebSocketDisconnect:
            bus.clients.discard(socket)

    @app.post('/api/v1/sources/{source_id}/check', status_code=202)
    async def check_source(source_id: str) -> dict[str, Any]:
        try: clickhouse_query('SELECT 1')
        except Exception as error: raise HTTPException(503, 'ClickHouse unavailable') from error
        with connect() as conn:
            event = record_event(conn, 'source', source_id, 'source.checked', {'id': source_id, 'status': 'available', 'checkedAt': now()})
            conn.execute('UPDATE sources SET status=%s, checked_at=%s WHERE id=%s', ('available', event['occurred_at'], source_id)); conn.commit()
        await bus.publish(event)
        return {'command_id': str(uuid4()), 'aggregate_id': source_id, 'accepted_event_id': event['event_id']}

    @app.post('/api/v1/runs', status_code=202)
    async def create_run(payload: RunCreate) -> dict[str, Any]:
        command_id = str(uuid4()); run_id = f'run-{uuid4()}'
        with connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT command_id,aggregate_id,accepted_event_id FROM commands WHERE idempotency_key=%s', (payload.idempotency_key,))
            existing = cur.fetchone()
            if existing: return {'command_id': existing[0], 'aggregate_id': existing[1], 'accepted_event_id': existing[2]}
            cur.execute('SELECT source_table,sandbox_database FROM benchmarks WHERE id=%s', (payload.benchmark_id,)); benchmark = cur.fetchone()
            if not benchmark: raise HTTPException(404, 'Benchmark not found')
            source_table, sandbox = benchmark
            cur.execute('INSERT INTO runs (id,benchmark_id,status,stage,started_at) VALUES (%s,%s,%s,%s,%s)', (run_id, payload.benchmark_id, 'running', 'baseline', now()))
            queued = record_event(conn, 'run', run_id, 'run.started', {'id': run_id, 'benchmarkId': payload.benchmark_id, 'status': 'running', 'stage': 'baseline', 'startedAt': now()}, command_id)
            cur.execute('INSERT INTO commands VALUES (%s,%s,%s,%s)', (payload.idempotency_key, command_id, run_id, queued['event_id'])); conn.commit()
        await bus.publish(queued)
        try:
            source_rows = int(clickhouse_query(f'SELECT count() FROM {source_table}').strip())
            clickhouse_query(f'DROP TABLE IF EXISTS {sandbox}.benchmark_events_candidate', sandbox=True, write=True)
            clickhouse_query(f'CREATE TABLE {sandbox}.benchmark_events_candidate AS {source_table}', sandbox=True, write=True)
            clickhouse_query(f'INSERT INTO {sandbox}.benchmark_events_candidate SELECT * FROM {source_table}', sandbox=True, write=True)
            candidate_rows = int(clickhouse_query(f'SELECT count() FROM {sandbox}.benchmark_events_candidate', sandbox=True).strip())
            with connect() as conn:
                conn.execute('UPDATE runs SET status=%s,stage=%s,source_rows=%s,candidate_rows=%s,finished_at=%s WHERE id=%s', ('completed', 'final_validation', source_rows, candidate_rows, now(), run_id))
                completed = record_event(conn, 'run', run_id, 'run.completed', {'id': run_id, 'status': 'completed', 'stage': 'final_validation', 'sourceRows': source_rows, 'candidateRows': candidate_rows, 'finishedAt': now()}, command_id); conn.commit()
            await bus.publish(completed)
        except Exception as error:
            with connect() as conn:
                conn.execute('UPDATE runs SET status=%s,stage=%s,failure_reason=%s,finished_at=%s WHERE id=%s', ('failed', 'failed', type(error).__name__, now(), run_id))
                failed = record_event(conn, 'run', run_id, 'run.failed', {'id': run_id, 'status': 'failed', 'stage': 'failed', 'finishedAt': now(), 'failureReason': type(error).__name__}, command_id); conn.commit()
            await bus.publish(failed)
        return {'command_id': command_id, 'aggregate_id': run_id, 'accepted_event_id': queued['event_id']}
    return app

app = create_app()
if __name__ == '__main__': uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)
