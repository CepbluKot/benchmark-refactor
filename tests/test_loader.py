import json
import tempfile
import unittest
from pathlib import Path

from loader import load_config, parse_config, parse_config_parts


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class LoaderTests(unittest.TestCase):
    def test_load_config_with_external_benchmarks_file(self) -> None:
        """Проверяет, что load config with external benchmarks file."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_json(
                base / "connections.json",
                {
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
            )
            _write_json(
                base / "rule_banks.json",
                {
                    "rule_banks": {
                        "default_bank": {
                            "column_rules": [
                                {
                                    "by_type": "UInt64",
                                    "types": ["UInt64", "UInt32"],
                                    "codecs": ["CODEC(Delta(8), LZ4)"],
                                }
                            ]
                        }
                    },
                    "default_rule_banks": {"clickhouse": "default_bank"},
                },
            )
            _write_json(
                base / "benchmarks.json",
                {
                    "benchmarks": [
                        {
                            "id": "bench_a",
                            "connection_id": "prod_ch",
                            "mode": "types",
                            "databases": ["analytics"],
                            "tables": ["events"],
                            "max_iterations": 3,
                        }
                    ]
                },
            )
            _write_json(
                base / "project.json",
                {
                    "connections_file": "connections.json",
                    "rule_banks_file": "rule_banks.json",
                    "benchmarks_file": "benchmarks.json",
                    "celery": {"workers": 3, "threads_per_worker": 1},
                },
            )

            config = load_config(base / "project.json")

            self.assertEqual(len(config.connections), 1)
            self.assertEqual(len(config.benchmarks), 1)
            self.assertEqual(config.default_rule_banks["clickhouse"], "default_bank")
            self.assertEqual(config.celery.workers, 3)
            self.assertEqual(config.celery.threads_per_worker, 1)

    def test_load_config_raises_for_unknown_connection_reference(self) -> None:
        """Проверяет, что load config raises for unknown connection reference."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_json(
                base / "connections.json",
                {
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
            )
            _write_json(base / "rule_banks.json", {"rule_banks": {}, "default_rule_banks": {}})
            _write_json(
                base / "project.json",
                {
                    "connections_file": "connections.json",
                    "rule_banks_file": "rule_banks.json",
                    "benchmarks": [
                        {
                            "id": "bench_bad",
                            "connection_id": "missing_conn",
                            "mode": "types",
                            "databases": ["analytics"],
                            "tables": ["events"],
                            "global_rules": {
                                "column_rules": [{"by_type": "UInt64", "types": ["UInt64"]}]
                            },
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, "connection_id"):
                load_config(base / "project.json")

    def test_parse_config_supports_relative_paths_via_base_dir(self) -> None:
        """Проверяет, что parse config supports relative paths via base dir."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_json(
                base / "connections.json",
                {
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
            )
            _write_json(
                base / "rule_banks.json",
                {
                    "rule_banks": {
                        "default_bank": {
                            "column_rules": [
                                {
                                    "by_type": "UInt64",
                                    "types": ["UInt64", "UInt32"],
                                    "codecs": ["CODEC(Delta(8), LZ4)"],
                                }
                            ]
                        }
                    },
                    "default_rule_banks": {"clickhouse": "default_bank"},
                },
            )
            project_raw = {
                "connections_file": "connections.json",
                "rule_banks_file": "rule_banks.json",
                "benchmarks": [
                    {
                        "id": "bench_inline",
                        "connection_id": "prod_ch",
                        "mode": "types",
                        "databases": ["analytics"],
                        "tables": ["events"],
                        "max_iterations": 1,
                    }
                ],
            }

            config = parse_config(project_raw, base_dir=base)
            self.assertEqual(config.benchmarks[0].id, "bench_inline")

    def test_parse_config_parts_with_inline_benchmarks(self) -> None:
        """Проверяет, что parse config parts with inline benchmarks."""
        config = parse_config_parts(
            celery_raw={
                "workers": 3,
                "threads_per_worker": 1,
            },
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
                        "id": "bench_inline_parts",
                        "connection_id": "prod_ch",
                        "mode": "types",
                        "databases": ["analytics"],
                        "tables": ["events"],
                        "global_rules": {
                            "column_rules": [
                                {
                                    "by_type": "UInt64",
                                    "types": ["UInt64", "UInt32"],
                                }
                            ]
                        },
                    }
                ]
            },
        )
        self.assertEqual(config.benchmarks[0].id, "bench_inline_parts")
        self.assertEqual(config.celery.workers, 3)

    def test_parse_config_parts_requires_valid_benchmarks_config(self) -> None:
        """Проверяет, что parse config parts requires valid benchmarks config."""
        with self.assertRaisesRegex(ValueError, "Ошибки в benchmarks-конфиге"):
            parse_config_parts(
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
                benchmarks_raw={},
            )

    def test_parse_config_parts_supports_split_configs(self) -> None:
        """Проверяет, что parse config parts supports split configs."""
        config = parse_config_parts(
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
            rule_banks_raw={
                "rule_banks": {},
                "default_rule_banks": {},
            },
            benchmarks_raw={
                "benchmarks": [
                    {
                        "id": "bench_env_parts",
                        "connection_id": "prod_ch",
                        "mode": "types",
                        "databases": ["analytics"],
                        "tables": ["events"],
                        "global_rules": {
                            "column_rules": [
                                {
                                    "by_type": "UInt64",
                                    "types": ["UInt64", "UInt32"],
                                }
                            ]
                        },
                    }
                ]
            },
        )
        self.assertEqual(config.celery.workers, 2)
        self.assertEqual(config.benchmarks[0].id, "bench_env_parts")


if __name__ == "__main__":
    unittest.main()
