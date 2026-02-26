import re
import unittest

from src.clickhouse_ddl import IndexDef, TableDDL


DDL = """
CREATE TABLE analytics.events
(
    `user_id` UInt64 CODEC(Delta(8), LZ4),
    `event_time` DateTime CODEC(DoubleDelta, ZSTD(1)),
    `country` LowCardinality(String) CODEC(ZSTD(1)),
    INDEX idx_user user_id TYPE minmax GRANULARITY 4
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""

COMPLEX_DDL = """
-- This is a header comment
CREATE TABLE IF NOT EXISTS analytics.events_ext ON CLUSTER `main_cluster`
(
    `id` UInt64 CODEC(Delta(8), LZ4),
    `ts` DateTime DEFAULT now() CODEC(DoubleDelta, ZSTD(1)),
    `payload` Nullable(String) COMMENT 'json payload',
    `attrs` Array(Tuple(UInt8, String)),
    INDEX idx_ts_hour toStartOfHour(ts) TYPE minmax GRANULARITY 2,
    PROJECTION p_ts (SELECT id, ts ORDER BY ts),
    CONSTRAINT c_positive CHECK id > 0
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/events_ext', '{replica}')
PARTITION BY toYYYYMM(ts)
PRIMARY KEY (id, ts)
ORDER BY (id, ts)
SAMPLE BY id
TTL ts + INTERVAL 7 DAY DELETE
SETTINGS index_granularity = 8192
COMMENT 'events extension'
;
"""

NESTED_TYPES_DDL = """
CREATE TABLE analytics.nested_types
(
    `price` Decimal(18,4),
    `state` Tuple(String, UInt8),
    `meta` Array(Tuple(UInt16, String))
)
ENGINE = MergeTree
ORDER BY tuple()
"""

INDEX_WITHOUT_TYPE_DDL = """
CREATE TABLE analytics.no_type_idx
(
    `x` UInt32,
    INDEX idx_x x
)
ENGINE = MergeTree
ORDER BY x
"""

PARAM_INDEX_DDL = """
CREATE TABLE analytics.param_idx
(
    `payload` String,
    INDEX idx_payload payload TYPE bloom_filter(0.01)
)
ENGINE = MergeTree
ORDER BY tuple()
"""

COMMENTED_DDL = """
-- before
CREATE TABLE analytics.comments_test
(
    -- user id line
    `user_id` UInt64,
    `ts` DateTime -- inline trailing comment
)
ENGINE = MergeTree
ORDER BY (user_id, ts)
;
"""

MULTI_GRANULARITY_SETTINGS_DDL = """
CREATE TABLE analytics.multi_granularity_settings
(
    `x` UInt64
)
ENGINE = MergeTree
ORDER BY x
SETTINGS index_granularity = 8192, allow_nullable_key = 1, index_granularity = 4096
"""

MULTI_SETTINGS_BLOCKS_DDL = """
CREATE TABLE analytics.multi_settings_blocks
(
    `x` UInt64
)
ENGINE = MergeTree
ORDER BY x
SETTINGS index_granularity = 8192
SETTINGS allow_nullable_key = 1, index_granularity = 4096
"""

CODEC_IN_COMMENT_DDL = """
CREATE TABLE analytics.codec_in_comment
(
    `msg` String COMMENT 'literal CODEC(ZSTD(1)) marker',
    `val` UInt32 CODEC(LZ4)
)
ENGINE = MergeTree
ORDER BY tuple()
"""

BLOCK_COMMENTS_DDL = """
/* header block comment with , and ( ) */
CREATE TABLE analytics.block_comments
(
    `a` String /* inline block comment, comma, keyword ORDER BY */,
    `b` UInt32 COMMENT 'a,b,c' /* tail block comment */
)
ENGINE = MergeTree
ORDER BY a
/* post-options block comment */
SETTINGS index_granularity = 8192
"""

TABLE_OPTIONS_KEYWORDS_IN_STRINGS_DDL = """
CREATE TABLE analytics.options_keywords
(
    `x` String
)
ENGINE = MergeTree
ORDER BY tuple()
SETTINGS custom_str = 'ORDER BY, COMMENT, SETTINGS, TTL', index_granularity = 8192
COMMENT 'This COMMENT mentions ORDER BY and SETTINGS'
"""

COMMENT_WITH_DASHES_DDL = """
CREATE TABLE analytics.comment_with_dashes
(
    `x` String COMMENT 'O''Reilly -- not a SQL comment, has comma, yes',
    `y` UInt8
)
ENGINE = MergeTree
ORDER BY y
"""

PROD_LOGS_ADQM_DDL = """
CREATE TABLE dm_core_1m.logs_adqm
(
    `timestamp` DateTime64(6, 'Europe/Moscow') COMMENT 'Datetime записи в текстовом файле',
    `message` String COMMENT 'Текст лога',
    `log_level` LowCardinality(String) COMMENT 'Уровень лога',
    `logger` LowCardinality(String) COMMENT 'Логирующая единица ADQM',
    `object` Nullable(String) COMMENT 'Объект, из-за которого появилась запись',
    `pid` UInt32 COMMENT 'pid',
    `something_in_curly_brackets` String COMMENT 'Странное пустое поле. Потом разберемся',
    `log_file_path` String COMMENT 'Путь и имя файла, в котором содержалась строка',
    `host_name` LowCardinality(String) COMMENT 'host',
    `_raw_message` Nullable(String) COMMENT 'Техническое поле для отладки Kafka',
    `_error` Nullable(String) COMMENT 'Техническое поле для отладки Kafka'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (log_level, timestamp)
SETTINGS index_granularity = 8192
"""

PROD_LOGS_DBT_DDL = """
CREATE TABLE dm_core_1m.logs_dbt
(
    `timestamp` DateTime64(6, 'UTC') COMMENT 'Время записи лога в файл',
    `dag` LowCardinality(String) COMMENT 'Имя дага',
    `task` String COMMENT 'Имя таска',
    `run` String COMMENT 'run_id',
    `msg` String COMMENT 'Сообщение лога',
    `log_level` LowCardinality(String) COMMENT 'Уровень лога',
    `log_class` LowCardinality(String) COMMENT 'Классификация лога. Сопоставляется с log_code',
    `log_code` LowCardinality(String) COMMENT 'Код лога. Сопоставляется с log_name',
    `log_invocation_id` UUID COMMENT 'invocation_id',
    `log_pid` UInt32 COMMENT 'PID',
    `dbt_target_user` LowCardinality(Nullable(String)) COMMENT 'Имя пользователя',
    `dbt_target_host` LowCardinality(Nullable(String)) COMMENT 'Имя хоста',
    `_filebeat_timestamp` DateTime64(6) COMMENT 'Дата-время попадания записи в Fluentbit',
    `_raw_message` Nullable(String) COMMENT 'техническое поле для отладки кафки',
    `_error` Nullable(String) COMMENT 'техническое поле для отладки кафки',
    `_clickhouse_timestamp` Nullable(DateTime('UTC'))
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (dag, task, timestamp)
SETTINGS index_granularity = 8192
"""

PROD_LOGS_AIRFLOW_DDL = """
CREATE TABLE dm_core_1m.logs_airflow
(
    `timestamp` DateTime64(6) COMMENT 'Дата-время попадания записи в Fluentbit',
    `dag` LowCardinality(String) COMMENT 'Имя дага',
    `run` String COMMENT 'Имя запуска',
    `task` String COMMENT 'Имя таска в формате "dag.task"',
    `attempt` UInt16 COMMENT 'Номер попытки запуска',
    `airflow_datetime` String COMMENT 'Дата-время лога Airflow',
    `airflow_python_logger_module` String COMMENT 'Имя логгера Airflow',
    `airflow_log_level` LowCardinality(String) COMMENT 'Уровень лога Airflow',
    `airflow_message` String COMMENT 'Сообщение Airflow с учетом конкатенации мультистрочных логов',
    `_raw_message` Nullable(String) COMMENT 'техническое поле для отладки кафки',
    `_error` Nullable(String) COMMENT 'техническое поле для отладки кафки'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (dag, run, task, attempt, timestamp)
SETTINGS index_granularity = 8192
"""

PROD_FLEX_LOADERS_DDL = """
CREATE TABLE raw_1m.log_flexloader_core_loaders
(
    `timestamp` DateTime64(6) COMMENT 'Datetime попадания лога в filebeat',
    `operation_type` LowCardinality(String) COMMENT 'ext или apl',
    `source_system` LowCardinality(Nullable(String)) COMMENT 'Система-источник',
    `table_name` LowCardinality(String) COMMENT 'Загружаемая таблица',
    `journal_id` Nullable(UInt32) COMMENT 'число journal_id, распарсенное из строки лога',
    `flex_msg` String COMMENT 'Сообщение лога, распарсенное из строки лога',
    `host_name` LowCardinality(String) COMMENT 'Имя хоста',
    `_raw_message` Nullable(String) COMMENT 'Техническое поле для отладки Kafka',
    `_error` Nullable(String) COMMENT 'Техническое поле для отладки Kafka'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (operation_type, table_name, timestamp)
SETTINGS index_granularity = 8192
"""

PROD_FLEX_SPARK_DDL = """
CREATE TABLE raw_1m.log_flexloader_core_spark
(
    `timestamp` DateTime64(6) COMMENT 'Datetime попадания лога в filebeat',
    `source_system` LowCardinality(String) COMMENT 'Система-источник',
    `table_name` LowCardinality(String) COMMENT 'Загружаемая таблица',
    `flex_msg` String COMMENT 'Сообщение лога, распарсенное из строки лога',
    `host_name` LowCardinality(String) COMMENT 'Имя хоста',
    `_raw_message` Nullable(String) COMMENT 'Техническое поле для отладки Kafka',
    `_error` Nullable(String) COMMENT 'Техническое поле для отладки Kafka'
)
ENGINE = MergeTree
PARTITION BY (toYYYYMM(timestamp), source_system)
ORDER BY (table_name, timestamp)
SETTINGS index_granularity = 8192
"""

PROD_K8S_AUDIT_DDL = """
CREATE TABLE raw_1m.log_k8s_audit
(
    `timestamp` DateTime64(6),
    `apiVersion` String,
    `auditID` String,
    `kind` String,
    `level` String,
    `objectRef_name` String,
    `objectRef_namespace` String,
    `objectRef_resource` String,
    `requestURI` String,
    `responseStatus_code` Int32,
    `sourceIPs` String,
    `stage` String,
    `user_groups` String,
    `user_username` String,
    `verb` String,
    `ext_ClusterEnv` String,
    `ext_ClusterName` String,
    `userAgent` String,
    `responseStatus_metadata` String,
    `annotations_authorization_reason` String,
    `responseStatus_message` String,
    `responseStatus_status` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (objectRef_namespace, timestamp)
SETTINGS index_granularity = 8192
"""

PROD_K8S_EVENTS_DDL = """
CREATE TABLE raw_1m.log_k8s_events
(
    `timestamp` DateTime64(6) COMMENT 'Временная метка',
    `message` String COMMENT 'Сообщение лога',
    `source_type` String COMMENT 'Тип источника',
    `ext_ClusterEnv` String COMMENT 'Окружение кластера',
    `ext_ClusterName` String COMMENT 'Имя кластера',
    `reason` String,
    `ext_ClusterEventType` String COMMENT 'Тип события кластера',
    `involvedObject_name` String,
    `involvedObject_namespace` String,
    `source_host` String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (involvedObject_namespace, timestamp)
SETTINGS index_granularity = 8192
"""

PROD_K8S_NOVA_DDL = """
CREATE TABLE raw_1m.log_k8s_nova_via_filebeat
(
    `timestamp` DateTime64(6) COMMENT 'Datetime попадания лога в filebeat',
    `message` String COMMENT 'Сообщение лога',
    `container_image` String COMMENT 'Образ контейнера',
    `container_name` LowCardinality(String) COMMENT 'Имя контейнера',
    `node` LowCardinality(String) COMMENT 'Нода k8s, на которой работал контейнер',
    `workspace` LowCardinality(String) COMMENT 'Воркспейс KubeSphere',
    `namespace` LowCardinality(String) COMMENT 'Неймспейс Kubernetes',
    `pod_name` String COMMENT 'Имя пода',
    `replicaset_name` Nullable(String) COMMENT 'Имя replicaset',
    `statefulset_name` Nullable(String) COMMENT 'Имя statefulset',
    `deployment_name` Nullable(String) COMMENT 'Имя deployment',
    `app` Nullable(String) COMMENT 'Имя app',
    `cm_service` Nullable(String) COMMENT 'Имя cm-service',
    `log_file_path` String COMMENT 'Путь и имя файла, в котором содержалась строка',
    `_raw_message` String COMMENT 'Техническое поле для отладки Kafka',
    `_error` String COMMENT 'Техническое поле для отладки Kafka'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (workspace, namespace, container_name, timestamp)
SETTINGS index_granularity = 8192
"""


class ClickHouseDDLTests(unittest.TestCase):
    def test_parse_extracts_columns_indexes_and_options(self) -> None:
        """Проверяет, что parse extracts columns indexes and options."""
        table = TableDDL.from_ddl(DDL)

        self.assertEqual(table.name, "analytics.events")
        self.assertEqual(len(table.columns), 3)
        self.assertEqual(len(table.indexes), 1)
        self.assertEqual(table.column("user_id").codec, "CODEC(Delta(8), LZ4)")
        self.assertEqual(table.index("idx_user").index_type, "minmax")
        self.assertEqual(table.index("idx_user").granularity, "4")
        self.assertEqual(table.engine, "MergeTree")
        self.assertEqual(table.order_by, "(user_id, event_time)")

    def test_copy_and_to_ddl_keep_original_unchanged(self) -> None:
        """Проверяет, что copy and to ddl keep original unchanged."""
        source = TableDDL.from_ddl(DDL)
        variant = source.copy()
        variant.column("user_id").type = "UInt32"
        variant.indexes.append(
            IndexDef(
                name="idx_country_bf",
                expr="country",
                index_type="bloom_filter(0.01)",
                granularity="2",
            )
        )
        rendered = variant.to_ddl()

        self.assertEqual(source.column("user_id").type, "UInt64")
        self.assertIn("`user_id` UInt32", rendered)
        self.assertIn(
            "INDEX idx_country_bf country TYPE bloom_filter(0.01) GRANULARITY 2",
            rendered,
        )

    def test_parse_complex_ddl_extracts_cluster_body_and_table_options(self) -> None:
        """Проверяет, что parse complex ddl extracts cluster body and table options."""
        table = TableDDL.from_ddl(COMPLEX_DDL)

        self.assertEqual(table.name, "analytics.events_ext")
        self.assertEqual(table.cluster, "main_cluster")
        self.assertEqual(table.engine, "ReplicatedMergeTree('/clickhouse/tables/{shard}/events_ext', '{replica}')")
        self.assertEqual(table.partition_by, "toYYYYMM(ts)")
        self.assertEqual(table.primary_key, "(id, ts)")
        self.assertEqual(table.order_by, "(id, ts)")
        self.assertEqual(table.sample_by, "id")

        self.assertEqual(len(table.columns), 4)
        self.assertEqual(len(table.indexes), 1)
        self.assertEqual(len(table.other_body_entries), 2)
        self.assertTrue(table.other_body_entries[0].startswith("PROJECTION "))
        self.assertTrue(table.other_body_entries[1].startswith("CONSTRAINT "))

        self.assertEqual(table.column("ts").extra, "DEFAULT now()")
        self.assertEqual(table.column("ts").codec, "CODEC(DoubleDelta, ZSTD(1))")
        self.assertEqual(table.column("payload").codec, None)
        self.assertEqual(table.column("payload").extra, "COMMENT 'json payload'")
        self.assertEqual(table.index("idx_ts_hour").expr, "toStartOfHour(ts)")
        self.assertEqual(table.index("idx_ts_hour").index_type, "minmax")
        self.assertEqual(table.index("idx_ts_hour").granularity, "2")

        self.assertEqual(
            table.other_table_options,
            [
                "TTL ts + INTERVAL 7 DAY DELETE",
                "SETTINGS index_granularity = 8192",
                "COMMENT 'events extension'",
            ],
        )

    def test_parse_preserves_nested_types_with_commas(self) -> None:
        """Проверяет, что parse preserves nested types with commas."""
        table = TableDDL.from_ddl(NESTED_TYPES_DDL)

        self.assertEqual([c.name for c in table.columns], ["price", "state", "meta"])
        self.assertEqual(table.column("price").type, "Decimal(18,4)")
        self.assertEqual(table.column("state").type, "Tuple(String, UInt8)")
        self.assertEqual(table.column("meta").type, "Array(Tuple(UInt16, String))")

    def test_parse_handles_missing_index_type(self) -> None:
        """Проверяет, что parse handles missing index type."""
        table = TableDDL.from_ddl(INDEX_WITHOUT_TYPE_DDL)

        self.assertEqual(len(table.indexes), 1)
        self.assertEqual(table.index("idx_x").expr, "x")
        self.assertEqual(table.index("idx_x").index_type, "")
        self.assertIsNone(table.index("idx_x").granularity)

    def test_parse_handles_parametric_index_type_without_granularity(self) -> None:
        """Проверяет, что parse handles parametric index type without granularity."""
        table = TableDDL.from_ddl(PARAM_INDEX_DDL)

        self.assertEqual(table.index("idx_payload").index_type, "bloom_filter(0.01)")
        self.assertIsNone(table.index("idx_payload").granularity)

    def test_parse_does_not_treat_codec_word_inside_comment_as_codec_clause(self) -> None:
        """Проверяет, что `CODEC(...)` внутри COMMENT не ломает парсинг колонки."""
        table = TableDDL.from_ddl(CODEC_IN_COMMENT_DDL)

        self.assertEqual(len(table.columns), 2)
        self.assertEqual(table.column("msg").codec, None)
        self.assertIn("CODEC(ZSTD(1))", table.column("msg").extra)
        self.assertEqual(table.column("val").codec, "CODEC(LZ4)")

    def test_parse_handles_block_comments_without_breaking_column_split(self) -> None:
        """Проверяет корректный парсинг DDL с block comments `/* ... */`."""
        table = TableDDL.from_ddl(BLOCK_COMMENTS_DDL)

        self.assertEqual(table.name, "analytics.block_comments")
        self.assertEqual([c.name for c in table.columns], ["a", "b"])
        self.assertEqual(table.get_index_granularity(), 8192)

    def test_parse_table_options_ignores_keywords_inside_string_literals(self) -> None:
        """Проверяет, что ORDER/COMMENT/SETTINGS внутри строк не дробят table options."""
        table = TableDDL.from_ddl(TABLE_OPTIONS_KEYWORDS_IN_STRINGS_DDL)

        self.assertEqual(table.engine, "MergeTree")
        self.assertEqual(table.order_by, "tuple()")
        self.assertEqual(
            table.other_table_options,
            [
                "SETTINGS custom_str = 'ORDER BY, COMMENT, SETTINGS, TTL', index_granularity = 8192",
                "COMMENT 'This COMMENT mentions ORDER BY and SETTINGS'",
            ],
        )
        self.assertEqual(table.get_index_granularity(), 8192)

    def test_parse_preserves_double_dash_inside_string_comment_literal(self) -> None:
        """Проверяет, что `--` внутри строкового COMMENT не воспринимается как SQL comment."""
        table = TableDDL.from_ddl(COMMENT_WITH_DASHES_DDL)

        self.assertEqual([c.name for c in table.columns], ["x", "y"])
        self.assertIn("-- not a SQL comment", table.column("x").extra)

    def test_parse_ignores_single_line_comments_and_semicolon(self) -> None:
        """Проверяет, что parse ignores single line comments and semicolon."""
        table = TableDDL.from_ddl(COMMENTED_DDL)

        self.assertEqual(table.name, "analytics.comments_test")
        self.assertEqual(len(table.columns), 2)
        self.assertEqual(table.column("user_id").type, "UInt64")
        self.assertEqual(table.column("ts").type, "DateTime")
        self.assertEqual(table.order_by, "(user_id, ts)")

    def test_to_ddl_orders_known_clauses_and_keeps_other_options(self) -> None:
        """Проверяет, что to ddl orders known clauses and keeps other options."""
        table = TableDDL.from_ddl(COMPLEX_DDL)
        rendered = table.to_ddl()

        engine_pos = rendered.index("\nENGINE = ")
        partition_pos = rendered.index("\nPARTITION BY ")
        pk_pos = rendered.index("\nPRIMARY KEY ")
        order_pos = rendered.index("\nORDER BY ")
        sample_pos = rendered.index("\nSAMPLE BY ")
        ttl_pos = rendered.index("\nTTL ")
        settings_pos = rendered.index("\nSETTINGS ")
        comment_pos = rendered.index("\nCOMMENT ")

        self.assertLess(engine_pos, partition_pos)
        self.assertLess(partition_pos, pk_pos)
        self.assertLess(pk_pos, order_pos)
        self.assertLess(order_pos, sample_pos)
        self.assertLess(sample_pos, ttl_pos)
        self.assertLess(ttl_pos, settings_pos)
        self.assertLess(settings_pos, comment_pos)

    def test_column_and_index_lookup_return_none_when_missing(self) -> None:
        """Проверяет, что column and index lookup return none when missing."""
        table = TableDDL.from_ddl(DDL)
        self.assertIsNone(table.column("missing_col"))
        self.assertIsNone(table.index("missing_idx"))

    def test_to_ddl_omits_codec_when_column_codec_is_none(self) -> None:
        """Проверяет, что to ddl omits codec when column codec is none."""
        table = TableDDL.from_ddl(DDL)
        table.column("user_id").codec = None

        rendered = table.to_ddl()
        self.assertIn("`user_id` UInt64", rendered)
        self.assertNotIn("`user_id` UInt64 CODEC", rendered)

    def test_from_ddl_raises_on_non_create_table_statement(self) -> None:
        """Проверяет, что from ddl raises on non create table statement."""
        with self.assertRaises(ValueError):
            TableDDL.from_ddl("SELECT 1")

    def test_from_ddl_raises_on_unbalanced_parentheses(self) -> None:
        """Проверяет, что from ddl raises on unbalanced parentheses."""
        bad_ddl = """
        CREATE TABLE analytics.bad
        (
            `x` Array(UInt8)
        ENGINE = MergeTree
        ORDER BY tuple()
        """
        with self.assertRaises(ValueError):
            TableDDL.from_ddl(bad_ddl)

    def test_set_index_granularity_updates_existing_settings(self) -> None:
        """Проверяет обновление существующего SETTINGS index_granularity."""
        table = TableDDL.from_ddl(COMPLEX_DDL)
        self.assertEqual(table.get_index_granularity(), 8192)

        table.set_index_granularity(16384)

        self.assertEqual(table.get_index_granularity(), 16384)
        self.assertIn("SETTINGS index_granularity = 16384", table.to_ddl())

    def test_set_index_granularity_adds_settings_when_missing(self) -> None:
        """Проверяет добавление SETTINGS index_granularity при его отсутствии."""
        table = TableDDL.from_ddl(DDL)
        self.assertIsNone(table.get_index_granularity())

        table.set_index_granularity(4096)

        self.assertEqual(table.get_index_granularity(), 4096)
        self.assertIn("SETTINGS index_granularity = 4096", table.to_ddl())

    def test_set_index_granularity_deduplicates_assignments_in_one_settings_block(self) -> None:
        """Проверяет дедупликацию index_granularity в одном SETTINGS-блоке."""
        table = TableDDL.from_ddl(MULTI_GRANULARITY_SETTINGS_DDL)
        table.set_index_granularity(16384)

        rendered = table.to_ddl()
        self.assertEqual(len(re.findall(r"index_granularity\s*=", rendered, flags=re.IGNORECASE)), 1)
        self.assertIn("allow_nullable_key = 1", rendered)
        self.assertEqual(table.get_index_granularity(), 16384)

    def test_set_index_granularity_removes_conflicts_from_all_settings_blocks(self) -> None:
        """Проверяет, что index_granularity не конфликтует даже при нескольких SETTINGS-блоках."""
        table = TableDDL.from_ddl(MULTI_SETTINGS_BLOCKS_DDL)
        table.set_index_granularity(12288)

        rendered = table.to_ddl()
        self.assertEqual(len(re.findall(r"index_granularity\s*=", rendered, flags=re.IGNORECASE)), 1)
        reparsed = TableDDL.from_ddl(rendered)
        self.assertEqual(reparsed.get_index_granularity(), 12288)

    def test_parse_prod_schemas_with_comments_and_complex_types(self) -> None:
        """Проверяет парсинг прод-схем с COMMENT, запятыми и сложными типами."""
        schemas = [
            (
                "dm_core_1m.logs_adqm",
                PROD_LOGS_ADQM_DDL,
                [
                    "timestamp",
                    "message",
                    "log_level",
                    "logger",
                    "object",
                    "pid",
                    "something_in_curly_brackets",
                    "log_file_path",
                    "host_name",
                    "_raw_message",
                    "_error",
                ],
            ),
            (
                "dm_core_1m.logs_dbt",
                PROD_LOGS_DBT_DDL,
                [
                    "timestamp",
                    "dag",
                    "task",
                    "run",
                    "msg",
                    "log_level",
                    "log_class",
                    "log_code",
                    "log_invocation_id",
                    "log_pid",
                    "dbt_target_user",
                    "dbt_target_host",
                    "_filebeat_timestamp",
                    "_raw_message",
                    "_error",
                    "_clickhouse_timestamp",
                ],
            ),
            (
                "dm_core_1m.logs_airflow",
                PROD_LOGS_AIRFLOW_DDL,
                [
                    "timestamp",
                    "dag",
                    "run",
                    "task",
                    "attempt",
                    "airflow_datetime",
                    "airflow_python_logger_module",
                    "airflow_log_level",
                    "airflow_message",
                    "_raw_message",
                    "_error",
                ],
            ),
            (
                "raw_1m.log_flexloader_core_loaders",
                PROD_FLEX_LOADERS_DDL,
                [
                    "timestamp",
                    "operation_type",
                    "source_system",
                    "table_name",
                    "journal_id",
                    "flex_msg",
                    "host_name",
                    "_raw_message",
                    "_error",
                ],
            ),
            (
                "raw_1m.log_flexloader_core_spark",
                PROD_FLEX_SPARK_DDL,
                [
                    "timestamp",
                    "source_system",
                    "table_name",
                    "flex_msg",
                    "host_name",
                    "_raw_message",
                    "_error",
                ],
            ),
            (
                "raw_1m.log_k8s_audit",
                PROD_K8S_AUDIT_DDL,
                [
                    "timestamp",
                    "apiVersion",
                    "auditID",
                    "kind",
                    "level",
                    "objectRef_name",
                    "objectRef_namespace",
                    "objectRef_resource",
                    "requestURI",
                    "responseStatus_code",
                    "sourceIPs",
                    "stage",
                    "user_groups",
                    "user_username",
                    "verb",
                    "ext_ClusterEnv",
                    "ext_ClusterName",
                    "userAgent",
                    "responseStatus_metadata",
                    "annotations_authorization_reason",
                    "responseStatus_message",
                    "responseStatus_status",
                ],
            ),
            (
                "raw_1m.log_k8s_events",
                PROD_K8S_EVENTS_DDL,
                [
                    "timestamp",
                    "message",
                    "source_type",
                    "ext_ClusterEnv",
                    "ext_ClusterName",
                    "reason",
                    "ext_ClusterEventType",
                    "involvedObject_name",
                    "involvedObject_namespace",
                    "source_host",
                ],
            ),
            (
                "raw_1m.log_k8s_nova_via_filebeat",
                PROD_K8S_NOVA_DDL,
                [
                    "timestamp",
                    "message",
                    "container_image",
                    "container_name",
                    "node",
                    "workspace",
                    "namespace",
                    "pod_name",
                    "replicaset_name",
                    "statefulset_name",
                    "deployment_name",
                    "app",
                    "cm_service",
                    "log_file_path",
                    "_raw_message",
                    "_error",
                ],
            ),
        ]

        for table_name, ddl, expected_columns in schemas:
            with self.subTest(table=table_name):
                parsed = TableDDL.from_ddl(ddl)
                self.assertEqual(parsed.name, table_name)
                self.assertEqual([c.name for c in parsed.columns], expected_columns)
                self.assertEqual(parsed.get_index_granularity(), 8192)

                rendered = parsed.to_ddl()
                reparsed = TableDDL.from_ddl(rendered)
                self.assertEqual([c.name for c in reparsed.columns], expected_columns)


if __name__ == "__main__":
    unittest.main()
