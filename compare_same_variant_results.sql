/* 
Сравнение запусков "один и тот же вариант" между legacy и phased.

Перед запуском при необходимости поменяй имена таблиц/БД под свои env:
  BENCH_RESULT_DATABASE
  BENCH_LEGACY_RESULT_TABLE
  BENCH_PHASED_RESULT_TABLE
*/

/* 1) Последние run_id по двум benchmark-id */
WITH
    (
        SELECT max(benchmark_run_id)
        FROM benchmark_results.benchmark_results
        WHERE benchmark_id = 'bench_same_variant_compare_legacy'
    ) AS legacy_run_id,
    (
        SELECT max(benchmark_run_id)
        FROM benchmark_results.benchmark_results__phased
        WHERE benchmark_id = 'bench_same_variant_compare_phased'
    ) AS phased_run_id
SELECT
    legacy_run_id,
    phased_run_id;

/* 2) Legacy: все варианты в последнем запуске (по score) */
WITH
    (
        SELECT max(benchmark_run_id)
        FROM benchmark_results.benchmark_results
        WHERE benchmark_id = 'bench_same_variant_compare_legacy'
    ) AS legacy_run_id
SELECT
    benchmark_run_id,
    benchmark_id,
    variant_mode,
    variant_table,
    score,
    tested_table_compression_overall_coef,
    tested_table_consumed_compressed_size_bytes_with_indexes_readable,
    source_table_consumed_compressed_size_bytes_overall_readable,
    tested_table_ddl,
    score_calculation_json
FROM benchmark_results.benchmark_results
WHERE benchmark_id = 'bench_same_variant_compare_legacy'
  AND benchmark_run_id = legacy_run_id
ORDER BY score DESC, variant_table;

/* 3) Phased: финальная фаза (phase=5) в последнем запуске */
WITH
    (
        SELECT max(benchmark_run_id)
        FROM benchmark_results.benchmark_results__phased
        WHERE benchmark_id = 'bench_same_variant_compare_phased'
    ) AS phased_run_id
SELECT
    benchmark_run_id,
    benchmark_id,
    phase,
    phase_name,
    rank_in_phase,
    is_top_n,
    variant_mode,
    variant_table,
    score,
    tested_table_compression_overall_coef,
    tested_table_consumed_compressed_size_bytes_with_indexes_readable,
    source_table_consumed_compressed_size_bytes_overall_readable,
    tested_table_ddl,
    score_calculation_json
FROM benchmark_results.benchmark_results__phased
WHERE benchmark_id = 'bench_same_variant_compare_phased'
  AND benchmark_run_id = phased_run_id
  AND phase = 5
ORDER BY rank_in_phase, score DESC;

/* 4) Быстрое сравнение top-1 legacy vs top-1 phased */
WITH
    (
        SELECT max(benchmark_run_id)
        FROM benchmark_results.benchmark_results
        WHERE benchmark_id = 'bench_same_variant_compare_legacy'
    ) AS legacy_run_id,
    (
        SELECT max(benchmark_run_id)
        FROM benchmark_results.benchmark_results__phased
        WHERE benchmark_id = 'bench_same_variant_compare_phased'
    ) AS phased_run_id,
    legacy_top AS (
        SELECT
            benchmark_run_id,
            score AS legacy_score,
            tested_table_compression_overall_coef AS legacy_compression_coef,
            tested_table_consumed_compressed_size_bytes_with_indexes AS legacy_size_bytes,
            tested_table_consumed_compressed_size_bytes_with_indexes_readable AS legacy_size_readable,
            tested_table_ddl AS legacy_tested_table_ddl
        FROM benchmark_results.benchmark_results
        WHERE benchmark_id = 'bench_same_variant_compare_legacy'
          AND benchmark_run_id = legacy_run_id
        ORDER BY score DESC
        LIMIT 1
    ),
    phased_top AS (
        SELECT
            benchmark_run_id,
            score AS phased_score,
            tested_table_compression_overall_coef AS phased_compression_coef,
            tested_table_consumed_compressed_size_bytes_with_indexes AS phased_size_bytes,
            tested_table_consumed_compressed_size_bytes_with_indexes_readable AS phased_size_readable,
            tested_table_ddl AS phased_tested_table_ddl
        FROM benchmark_results.benchmark_results__phased
        WHERE benchmark_id = 'bench_same_variant_compare_phased'
          AND benchmark_run_id = phased_run_id
          AND phase = 5
        ORDER BY rank_in_phase ASC, score DESC
        LIMIT 1
    )
SELECT *
FROM legacy_top
CROSS JOIN phased_top;
