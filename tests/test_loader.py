import json
import tempfile
import unittest
from pathlib import Path

from loader import load_config, parse_config


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class LoaderTests(unittest.TestCase):
    def test_load_config_with_external_benchmarks_file(self) -> None:
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


if __name__ == "__main__":
    unittest.main()

