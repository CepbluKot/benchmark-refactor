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


if __name__ == "__main__":
    unittest.main()
