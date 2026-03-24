import unittest

from src.benchmark_runtime.implementations.table_strategy.sequential_phased_topn import (
    _build_top_choice_maps,
)


class SequentialPhasedTopNMergeTests(unittest.TestCase):
    def test_build_top_choice_maps_guarantees_top1_combo_for_max_mode(self) -> None:
        options_by_column = {
            "col_a": [(10.0, "a_top"), (9.0, "a_second")],
            "col_b": [(8.0, "b_top"), (1.0, "b_second")],
            "col_c": [(7.0, "c_top"), (2.0, "c_second")],
        }

        merged = _build_top_choice_maps(
            options_by_column,
            limit=1,
            prefer_higher_score=True,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0][1],
            {"col_a": "a_top", "col_b": "b_top", "col_c": "c_top"},
        )

    def test_build_top_choice_maps_guarantees_top1_combo_for_min_mode(self) -> None:
        options_by_column = {
            "col_a": [(1.0, "a_top"), (3.0, "a_second")],
            "col_b": [(2.0, "b_top"), (5.0, "b_second")],
            "col_c": [(0.5, "c_top"), (4.0, "c_second")],
        }

        merged = _build_top_choice_maps(
            options_by_column,
            limit=1,
            prefer_higher_score=False,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0][1],
            {"col_a": "a_top", "col_b": "b_top", "col_c": "c_top"},
        )


if __name__ == "__main__":
    unittest.main()
