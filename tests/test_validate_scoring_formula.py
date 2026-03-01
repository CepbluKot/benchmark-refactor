import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Dict

from validate_scoring_formula import main


def _write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _benchmarks_payload(expression: str) -> Dict:
    return {
        "benchmarks": [
            {
                "id": "bench_formula",
                "connection_id": "prod_ch",
                "strategy": "types_strategy",
                "databases": ["analytics"],
                "tables": ["events"],
                "global_rules": {
                    "column_rules": [{"by_type": "UInt64", "types": ["UInt64", "UInt32"]}]
                },
                "scoring": {
                    "mode": "expression",
                    "expression": expression,
                },
            }
        ]
    }


class ValidateScoringFormulaCliTests(unittest.TestCase):
    def test_returns_zero_for_valid_formula(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            benchmarks_path = Path(tmp) / "benchmarks.json"
            _write_json(
                benchmarks_path,
                _benchmarks_payload("safe_div(tested.select.time_ms_percentiles[0], 2)"),
            )

            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(
                    [
                        "--path",
                        str(benchmarks_path),
                        "--type",
                        "benchmarks",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertIn("OK: scoring.expression валиден", out.getvalue())
            self.assertEqual(err.getvalue(), "")

    def test_returns_zero_for_valid_formula_with_median(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            benchmarks_path = Path(tmp) / "benchmarks.json"
            _write_json(
                benchmarks_path,
                _benchmarks_payload("safe_div(median(tested.select.time_ms_percentiles), 2)"),
            )

            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(
                    [
                        "--path",
                        str(benchmarks_path),
                        "--type",
                        "benchmarks",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertIn("OK: scoring.expression валиден", out.getvalue())
            self.assertEqual(err.getvalue(), "")

    def test_returns_zero_for_valid_formula_with_min_max(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            benchmarks_path = Path(tmp) / "benchmarks.json"
            _write_json(
                benchmarks_path,
                _benchmarks_payload("safe_div(max(tested.select.time_ms_percentiles), min(2, 4))"),
            )

            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(
                    [
                        "--path",
                        str(benchmarks_path),
                        "--type",
                        "benchmarks",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertIn("OK: scoring.expression валиден", out.getvalue())
            self.assertEqual(err.getvalue(), "")

    def test_returns_non_zero_for_invalid_formula(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            benchmarks_path = Path(tmp) / "benchmarks.json"
            _write_json(
                benchmarks_path,
                _benchmarks_payload("unknown_root.select.time_ms_percentiles[0]"),
            )

            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(
                    [
                        "--path",
                        str(benchmarks_path),
                        "--type",
                        "benchmarks",
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertEqual(out.getvalue(), "")
            self.assertIn("WARNING: найдены ошибки scoring.expression", err.getvalue())
            self.assertIn("benchmark=bench_formula", err.getvalue())

    def test_returns_non_zero_for_invalid_stage_formula(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            benchmarks_path = Path(tmp) / "benchmarks.json"
            payload = _benchmarks_payload("safe_div(2, 1)")
            payload["benchmarks"][0]["scoring"]["by_stage"] = {
                "types": {
                    "mode": "expression",
                    "expression": "unknown_root.select.time_ms_percentiles[0]",
                }
            }
            _write_json(benchmarks_path, payload)

            out = StringIO()
            err = StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(
                    [
                        "--path",
                        str(benchmarks_path),
                        "--type",
                        "benchmarks",
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertEqual(out.getvalue(), "")
            self.assertIn("WARNING: найдены ошибки scoring.expression", err.getvalue())
            self.assertIn("benchmark=bench_formula, stage=types", err.getvalue())


if __name__ == "__main__":
    unittest.main()
