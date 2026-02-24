import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Dict

from validate_json_config import main


def _write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _celery_payload() -> Dict:
    return {"workers": 4, "threads_per_worker": 2}


def _connections_payload(connection_id: str = "prod_ch") -> Dict:
    return {
        "connections": [
            {
                "id": connection_id,
                "dbms": "clickhouse",
                "credential_type": "password",
                "host": "localhost",
                "port": 9000,
                "login": "bench_user",
                "password": "secret",
            }
        ]
    }


def _rule_banks_payload(bank_id: str = "baseline_bank") -> Dict:
    return {
        "rule_banks": {
            bank_id: {
                "column_rules": [{"by_type": "UInt64", "types": ["UInt64", "UInt32"]}]
            }
        },
        "default_rule_banks": {"clickhouse": bank_id},
    }


def _benchmarks_payload(
    connection_id: str = "prod_ch",
    rule_bank: str = "baseline_bank",
) -> Dict:
    return {
        "benchmarks": [
            {
                "id": "bench_types",
                "connection_id": connection_id,
                "mode": "types",
                "databases": ["analytics"],
                "tables": ["events"],
                "global_rules": {"rule_bank": rule_bank},
            }
        ]
    }


class ValidateJsonConfigCliTests(unittest.TestCase):
    def test_single_mode_supports_all_config_types(self) -> None:
        """Проверяет, что single mode supports all config types."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            celery_path = base / "celery.json"
            connections_path = base / "connections.json"
            rule_banks_path = base / "rule_banks.json"
            benchmarks_path = base / "benchmarks.json"
            project_path = base / "project.json"
            root_path = base / "root.json"

            _write_json(celery_path, _celery_payload())
            _write_json(connections_path, _connections_payload())
            _write_json(rule_banks_path, _rule_banks_payload())
            _write_json(benchmarks_path, _benchmarks_payload())
            _write_json(
                project_path,
                {
                    "connections_file": "connections.json",
                    "rule_banks_file": "rule_banks.json",
                    "benchmarks_file": "benchmarks.json",
                },
            )
            _write_json(
                root_path,
                {
                    "connections": _connections_payload()["connections"],
                    "benchmarks": _benchmarks_payload()["benchmarks"],
                    "rule_banks": _rule_banks_payload()["rule_banks"],
                    "default_rule_banks": _rule_banks_payload()["default_rule_banks"],
                    "celery": _celery_payload(),
                },
            )

            variants = [
                ("celery", celery_path),
                ("connections", connections_path),
                ("rule_banks", rule_banks_path),
                ("benchmarks", benchmarks_path),
                ("project", project_path),
                ("root", root_path),
            ]
            for cfg_type, path in variants:
                out = StringIO()
                err = StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = main(
                        [
                            "single",
                            "--type",
                            cfg_type,
                            "--path",
                            str(path),
                        ]
                    )
                self.assertEqual(rc, 0)
                self.assertIn("OK:", out.getvalue())
                self.assertEqual(err.getvalue(), "")

    def test_project_mode_validates_file_references(self) -> None:
        """Проверяет, что project mode validates file references."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_json(base / "celery.json", _celery_payload())
            _write_json(base / "connections.json", _connections_payload())
            _write_json(base / "rule_banks.json", _rule_banks_payload())
            _write_json(base / "benchmarks.json", _benchmarks_payload())
            project_path = base / "project.json"
            _write_json(
                project_path,
                {
                    "connections_file": "connections.json",
                    "rule_banks_file": "rule_banks.json",
                    "benchmarks_file": "benchmarks.json",
                    "celery": _celery_payload(),
                },
            )

            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(["project", "--path", str(project_path)])

            self.assertEqual(rc, 0)
            self.assertIn("project-конфиг", out.getvalue())
            self.assertEqual(err.getvalue(), "")

    def test_parts_mode_returns_error_for_broken_cross_reference(self) -> None:
        """Проверяет, что parts mode returns error for broken cross reference."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            celery_path = base / "celery.json"
            connections_path = base / "connections.json"
            rule_banks_path = base / "rule_banks.json"
            benchmarks_path = base / "benchmarks.json"

            _write_json(celery_path, _celery_payload())
            _write_json(connections_path, _connections_payload(connection_id="prod_ch"))
            _write_json(rule_banks_path, _rule_banks_payload(bank_id="baseline_bank"))
            _write_json(
                benchmarks_path,
                _benchmarks_payload(
                    connection_id="missing_connection",
                    rule_bank="baseline_bank",
                ),
            )

            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(
                    [
                        "parts",
                        "--celery-path",
                        str(celery_path),
                        "--connections-path",
                        str(connections_path),
                        "--rule-banks-path",
                        str(rule_banks_path),
                        "--benchmarks-path",
                        str(benchmarks_path),
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertEqual(out.getvalue(), "")
            self.assertIn("connection_id", err.getvalue())


if __name__ == "__main__":
    unittest.main()
