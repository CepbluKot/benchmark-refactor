import unittest

from main import _apply_default_test_database
from src.loader import parse_config_parts


class MainTestDatabaseEnvTests(unittest.TestCase):
    def _root_config(self):
        return parse_config_parts(
            celery_raw={"workers": 2, "threads_per_worker": 1},
            connections_raw={
                "connections": [
                    {
                        "id": "prod_ch",
                        "dbms": "clickhouse",
                        "credential_type": "password",
                        "host": "localhost",
                        "port": 9000,
                        "login": "user",
                        "password": "pass",
                    }
                ]
            },
            rule_banks_raw={"rule_banks": {}, "default_rule_banks": {}},
            benchmarks_raw={
                "benchmarks": [
                    {
                        "id": "bench_without_test_db",
                        "connection_id": "prod_ch",
                        "strategy": "types_strategy",
                        "databases": ["analytics"],
                        "tables": ["events"],
                        "global_rules": {
                            "column_rules": [
                                {"by_type": "UInt64", "types": ["UInt64", "UInt32"]}
                            ]
                        },
                    },
                    {
                        "id": "bench_with_own_test_db",
                        "connection_id": "prod_ch",
                        "strategy": "types_strategy",
                        "databases": ["analytics"],
                        "tables": ["events"],
                        "test_database": "bench_custom",
                        "global_rules": {
                            "column_rules": [
                                {"by_type": "UInt64", "types": ["UInt64", "UInt32"]}
                            ]
                        },
                    },
                ]
            },
        )

    def test_apply_default_test_database_sets_only_missing_values(self) -> None:
        """Проверяет, что env fallback применяет test_database только там, где его нет."""
        config = self._root_config()

        applied = _apply_default_test_database(config, "bench_env")

        self.assertEqual(applied, 1)
        self.assertEqual(config.benchmarks[0].test_database, "bench_env")
        self.assertEqual(config.benchmarks[1].test_database, "bench_custom")

    def test_apply_default_test_database_is_noop_for_empty_value(self) -> None:
        """Проверяет, что пустой env fallback не меняет конфиг."""
        config = self._root_config()

        applied = _apply_default_test_database(config, None)

        self.assertEqual(applied, 0)
        self.assertIsNone(config.benchmarks[0].test_database)
        self.assertEqual(config.benchmarks[1].test_database, "bench_custom")


if __name__ == "__main__":
    unittest.main()

