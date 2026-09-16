/**
 * Демонстрационное наполнение редактора.
 *
 * Первый бенчмарк — копия реального файла проекта
 * `configs/hits_postgres/benchmarks.hits_postgres.sequential_topn.local.json`.
 * Второй добавлен как пример стратегии `types_strategy` с ручными запросами.
 *
 * Файл подключений приведён без реальных адресов и паролей.
 */

export const SAMPLE_FILE_NAME = 'benchmarks.hits_postgres.sequential_topn.local.json';

export const SAMPLE_FILE_PATH =
  'configs/hits_postgres/benchmarks.hits_postgres.sequential_topn.local.json';

export const SAMPLE_BENCHMARKS_JSON = `{
  "benchmarks": [
    {
      "id": "bench_hits_postgres_sequential_topn",
      "connection_id": "local_ch_hits",
      "strategy": "sequential_phased_topn_strategy",
      "column_rules_mode": "inline_only",
      "index_rules_mode": "inline_only",
      "column_order_mode": "compressed_size_desc",
      "order_by_first": "event_date",
      "order_by_candidates": [
        "event_date"
      ],
      "tables": {
        "default": [
          "hits_postgres"
        ]
      },
      "test_database": "benchmark_tmp",
      "insert_operations_count": 5,
      "sequential_top_n_limits": {
        "order_by": 3,
        "types": 3,
        "codecs": 3,
        "index_granularity": 3,
        "indexes": 3,
        "final_validation": 3
      },
      "final_validation_input_top_n": 3,
      "max_winners_per_parent_limits": {
        "types": 3,
        "codecs": 3,
        "indexes": 3
      },
      "scoring": {
        "mode": "expression",
        "expression": "exp(0.75 * ln(select_ratio) + 0.25 * ln(compression_ratio))",
        "on_error_score": -1.0,
        "variables": {
          "baseline_median_read_bytes": "medians.source_select_read_bytes",
          "test_median_read_bytes": "medians.tested_select_read_bytes",
          "select_ratio": "safe_div(baseline_median_read_bytes, test_median_read_bytes, 1.0)",
          "compression_ratio": "safe_div(source_size_bytes, tested_size_bytes, 1.0)"
        }
      },
      "max_benchmarks_limits": {
        "order_by": 10,
        "types": 2,
        "codecs": 5,
        "index_granularity": 10,
        "indexes": 10,
        "indexes_validation": 10,
        "final_validation": 10,
        "sequential": 20
      },
      "index_granularity_values": [
        8192,
        16384
      ],
      "source_insert_rows_per_operation_limits": {
        "sequential": 100000
      },
      "insert_rows_per_operation_limits": {
        "types": 100000,
        "indexes": 100000,
        "sequential": 100000
      },
      "global_rules": {
        "order_by_rules": {
          "first_column": "event_date",
          "candidates": [
            "event_date",
            "country"
          ],
          "auto_generate_candidates": false
        },
        "column_rules": [],
        "index_rules": [
          {
            "by_name": "page_url",
            "by_type": "String",
            "auto_generate_indexes": false,
            "indexes": [
              {
                "type": "ngrambf_v1(3, 32768, 3, 0)",
                "granularity": [
                  4,
                  8,
                  16
                ],
                "index_granularity_values": [
                  8192,
                  16384
                ]
              }
            ]
          },
          {
            "by_name": "country",
            "by_type": "String",
            "auto_generate_indexes": false,
            "indexes": [
              {
                "type": "ngrambf_v1(3, 32768, 3, 0)",
                "granularity": [
                  4,
                  8,
                  16
                ],
                "index_granularity_values": [
                  8192,
                  16384
                ]
              }
            ]
          }
        ]
      },
      "table_rules": [],
      "queries": {
        "mode": "auto",
        "auto_like_on_measured_columns": true,
        "auto_like_sample_rows_per_column": 20,
        "auto_like_min_token_length": 3,
        "auto_like_max_token_length": 24,
        "auto_select_limit": 10,
        "auto_select_operations_count": 5,
        "auto_include_miss_queries": true
      }
    },
    {
      "id": "bench_types_only_example",
      "connection_id": "local_ch_hits",
      "strategy": "types_strategy",
      "databases": [
        "analytics"
      ],
      "tables": [
        "user_events"
      ],
      "test_database": "benchmark_tmp",
      "insert_operations_count": 10,
      "insert_rows_per_operation_limits": {
        "types": 200000
      },
      "global_rules": {
        "column_rules": [
          {
            "by_type": "UInt64",
            "types": [
              "UInt64",
              "UInt32"
            ],
            "codecs": [
              "CODEC(Delta(8), LZ4)",
              "CODEC(T64, ZSTD(1))"
            ]
          },
          {
            "by_type": "DateTime",
            "by_name": "event_date",
            "codecs": [
              "CODEC(DoubleDelta, LZ4)",
              "CODEC(DoubleDelta, ZSTD(1))"
            ]
          }
        ]
      },
      "queries": {
        "mode": "manual",
        "test_queries": [
          {
            "query_id": "q_country_hit",
            "query": "SELECT count() FROM {table} WHERE country = 'DE'",
            "query_type": "hit",
            "cache_mode": "warm",
            "select_operations_count": 5,
            "warmup_queries": [
              "SELECT count() FROM {table}"
            ]
          },
          {
            "query_id": "q_page_url_cold",
            "query": "SELECT page_url FROM {table} WHERE page_url LIKE '%/checkout%' LIMIT 10",
            "query_type": "hit",
            "cache_mode": "cold",
            "select_operations_count": 3
          }
        ]
      },
      "scoring": {
        "mode": "expression",
        "expression": "exp(0.75 * ln(select_ratio) + 0.25 * ln(compression_ratio))",
        "on_error_score": -1.0,
        "variables": {
          "baseline_median_read_bytes": "medians.source_select_read_bytes",
          "test_median_read_bytes": "medians.tested_select_read_bytes",
          "select_ratio": "safe_div(baseline_median_read_bytes, test_median_read_bytes, 1.0)",
          "compression_ratio": "safe_div(source_size_bytes, tested_size_bytes, 1.0)"
        }
      },
      "table_rules": [
        {
          "database": "analytics",
          "table": "user_events",
          "insert_operations_count": 5,
          "rules": {
            "column_order": {
              "event_date": 1,
              "country": 2
            }
          }
        }
      ]
    }
  ]
}
`;

export const SAMPLE_CONNECTIONS_JSON = `{
  "connections": [
    {
      "id": "local_ch_hits",
      "dbms": "clickhouse",
      "credential_type": "password",
      "host": "clickhouse.internal",
      "port": 8123,
      "login": "bench_user",
      "password": "<задаётся при развёртывании>"
    }
  ]
}
`;
