import unittest

from settings import AppSettings


class SettingsTests(unittest.TestCase):
    @staticmethod
    def _required_base_kwargs() -> dict:
        # {} в base64
        empty_json_b64 = "e30="
        return {
            "celery_config_b64": empty_json_b64,
            "connections_config_b64": empty_json_b64,
            "rule_banks_config_b64": empty_json_b64,
            "benchmarks_config_b64": empty_json_b64,
        }

    def test_benchmark_ids_csv_is_parsed(self) -> None:
        """Проверяет, что benchmark ids csv is parsed."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            benchmark_ids="bench_a, bench_b ,bench_c",
        )
        self.assertEqual(settings.benchmark_ids, ["bench_a", "bench_b", "bench_c"])

    def test_benchmark_ids_json_array_is_parsed(self) -> None:
        """Проверяет, что benchmark ids json array is parsed."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            benchmark_ids='["bench_x", "bench_y"]',
        )
        self.assertEqual(settings.benchmark_ids, ["bench_x", "bench_y"])

    def test_required_base64_field_must_not_be_empty(self) -> None:
        """Проверяет, что required base64 field must not be empty."""
        with self.assertRaises(ValueError):
            AppSettings(
                _env_file=None,
                celery_config_b64="  ",
                connections_config_b64="e30=",
                rule_banks_config_b64="e30=",
                benchmarks_config_b64="e30=",
            )

    def test_decode_celery_config_rejects_invalid_base64(self) -> None:
        """Проверяет, что decode celery config rejects invalid base64."""
        settings = AppSettings(
            _env_file=None,
            celery_config_b64="not_base64",
            connections_config_b64="e30=",
            rule_banks_config_b64="e30=",
            benchmarks_config_b64="e30=",
        )
        with self.assertRaises(ValueError):
            settings.decode_celery_config()

    def test_test_database_is_trimmed(self) -> None:
        """Проверяет, что test_database trimится и сохраняется."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            test_database="  bench_tmp  ",
        )
        self.assertEqual(settings.test_database, "bench_tmp")

    def test_test_database_empty_string_becomes_none(self) -> None:
        """Проверяет, что пустой test_database трактуется как отсутствие override."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            test_database="   ",
        )
        self.assertIsNone(settings.test_database)

    def test_result_connection_id_is_trimmed(self) -> None:
        """Проверяет, что result_connection_id trimится."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            result_connection_id="  prod_ch  ",
        )
        self.assertEqual(settings.result_connection_id, "prod_ch")

    def test_result_target_must_not_be_empty(self) -> None:
        """Проверяет, что result_database/result_table не могут быть пустыми."""
        with self.assertRaises(ValueError):
            AppSettings(
                _env_file=None,
                **self._required_base_kwargs(),
                result_database="  ",
            )

        with self.assertRaises(ValueError):
            AppSettings(
                _env_file=None,
                **self._required_base_kwargs(),
                result_table="  ",
            )

    def test_resolved_result_tables_defaults(self) -> None:
        """Проверяет default-resolve таблиц legacy/phased."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            result_table="combined_results",
        )
        self.assertEqual(settings.resolved_legacy_result_table, "combined_results")
        self.assertEqual(settings.resolved_phased_result_table, "combined_results__phased")
        self.assertEqual(settings.resolved_phased_runs_table, "benchmark_runs")

    def test_optional_result_table_overrides_are_trimmed(self) -> None:
        """Проверяет trim optional override-полей таблиц result store."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            legacy_result_table="  legacy_tbl  ",
            phased_result_table="  phased_tbl  ",
            phased_runs_table="  phased_runs  ",
        )
        self.assertEqual(settings.resolved_legacy_result_table, "legacy_tbl")
        self.assertEqual(settings.resolved_phased_result_table, "phased_tbl")
        self.assertEqual(settings.resolved_phased_runs_table, "phased_runs")

    def test_resume_incomplete_run_flag_is_parsed(self) -> None:
        """Проверяет чтение BENCH_RESUME_INCOMPLETE_RUN как bool."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            resume_incomplete_run="1",
        )
        self.assertTrue(settings.resume_incomplete_run)

    def test_keep_alive_after_run_flag_is_parsed(self) -> None:
        """Проверяет чтение BENCH_KEEP_ALIVE_AFTER_RUN как bool."""
        settings = AppSettings(
            _env_file=None,
            **self._required_base_kwargs(),
            keep_alive_after_run="true",
        )
        self.assertTrue(settings.keep_alive_after_run)


if __name__ == "__main__":
    unittest.main()
