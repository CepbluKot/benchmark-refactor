import unittest

from src.benchmark_runtime.implementations.clickhouse_celery.scoring import (
    ScoreEvaluationError,
    build_percentile_lookup,
    evaluate_score_expression,
    validate_score_expression,
)


class ClickHouseCeleryScoringExpressionTests(unittest.TestCase):
    def test_build_percentile_lookup_supports_numeric_and_string_keys(self) -> None:
        lookup = build_percentile_lookup([50, 95, 100], [10.0, 20.0, 30.0])
        self.assertEqual(lookup[95], 20.0)
        self.assertEqual(lookup["95"], 20.0)
        self.assertEqual(lookup["p95"], 20.0)

    def test_expression_supports_indexed_percentile_arrays(self) -> None:
        context = {
            "source": {
                "select": {
                    "time_ms_percentiles": [150.0, 200.0],
                }
            },
            "tested": {
                "select": {
                    "time_ms_percentiles": [75.0, 100.0],
                }
            },
        }
        score = evaluate_score_expression(
            "safe_div(source.select.time_ms_percentiles[1], tested.select.time_ms_percentiles[1])",
            context,
        )
        self.assertEqual(score, 2.0)

    def test_expression_supports_percentile_lookup(self) -> None:
        source_map = build_percentile_lookup([50, 100], [150.0, 200.0])
        tested_map = build_percentile_lookup([50, 100], [75.0, 100.0])
        score = evaluate_score_expression(
            "safe_div(pct(source_map, 100), pct(tested_map, 'p100'))",
            {
                "source_map": source_map,
                "tested_map": tested_map,
            },
        )
        self.assertEqual(score, 2.0)

    def test_expression_rejects_unsafe_calls(self) -> None:
        with self.assertRaises(ScoreEvaluationError):
            evaluate_score_expression("__import__('os').system('echo x')", {})

    def test_expression_raises_on_unknown_name(self) -> None:
        with self.assertRaises(ScoreEvaluationError):
            evaluate_score_expression("unknown_name + 1", {})

    def test_expression_raises_on_out_of_range_index(self) -> None:
        with self.assertRaises(ScoreEvaluationError):
            evaluate_score_expression("values[10]", {"values": [1.0, 2.0]})

    def test_expression_supports_parentheses_sqrt_ln_and_power_operator(self) -> None:
        score = evaluate_score_expression(
            "(sqrt((16)) + ln(1)) * (2 ** 3)",
            {},
        )
        self.assertEqual(score, 32.0)

    def test_expression_supports_pow_function_alias(self) -> None:
        score = evaluate_score_expression("pow(3, 2)", {})
        self.assertEqual(score, 9.0)

    def test_static_validation_accepts_supported_expression(self) -> None:
        issues = validate_score_expression(
            "safe_div(pct(tested_select_time_ms_by_percentile, 95), 2)",
        )
        self.assertEqual(issues, [])

    def test_static_validation_reports_unknown_root_name(self) -> None:
        issues = validate_score_expression("foo.select.time_ms_percentiles[0]")
        self.assertTrue(issues)
        self.assertIn("Неизвестное имя 'foo'", " | ".join(issues))

    def test_static_validation_reports_unsupported_function(self) -> None:
        issues = validate_score_expression("unknown_func(1)")
        self.assertTrue(issues)
        self.assertIn("не поддерживается", " | ".join(issues))


if __name__ == "__main__":
    unittest.main()
