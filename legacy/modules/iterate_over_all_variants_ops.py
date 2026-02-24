import itertools
import logging
from typing import Dict, Iterable, List, Sequence, Tuple

from modules.data_type_alternatives import string_alternatives
from modules.indexes_alternatives import ngrambf_v1_params
from modules.interfaces import (
    DatabaseCol,
    DataTypeAlternatives,
    IndexType,
    PermutationTactics,
)

logger = logging.getLogger(__name__)


def get_variants_for_specified_col_and_type(
    selected_cols: List[DatabaseCol],
    alternatives: List[DatabaseCol],
    data_type_permutation_mode: PermutationTactics,
) -> Iterable[Tuple[DatabaseCol, ...]]:
    """selected_cols - колонки 1 типа (+ выбранные по названию, если требуется)"""
    n_cols = len(selected_cols)
    if not selected_cols:
        return []
    if data_type_permutation_mode == PermutationTactics.PRODUCT_PERMUTATIONS:
        for comb in itertools.product(alternatives, repeat=n_cols):
            yield comb
    elif data_type_permutation_mode == PermutationTactics.UNIFORM_PERMUTATION:
        for alt in alternatives:
            yield tuple([alt] * n_cols)


def iterate_over_all_data_compression_variants(
    cols_list: Sequence[DatabaseCol], alternatives: Dict[str, DataTypeAlternatives]
) -> Iterable[List[DatabaseCol]]:
    groups_of_vars_for_change: Dict[str, List[DatabaseCol]] = {}
    groups_of_vars_not_for_change: Dict[str, List[DatabaseCol]] = {}

    cols_to_append = []
    for col in cols_list:
        if col.other_params and not col.name and not col.datatype and not col.codec:
            cols_to_append.append(col)

    for col in cols_list:
        if col.datatype in alternatives:
            if (
                "*" in alternatives[col.datatype].allowed_cols_names
                or col.name in alternatives[col.datatype].allowed_cols_names
            ):
                if col.datatype not in groups_of_vars_for_change:
                    groups_of_vars_for_change[col.datatype] = []
                groups_of_vars_for_change[col.datatype].append(col)
                continue
        if col.datatype not in groups_of_vars_not_for_change:
            groups_of_vars_not_for_change[col.datatype] = []
        groups_of_vars_not_for_change[col.datatype].append(col)

    full_info_for_creating_combos: List[
        Tuple[str, List[DatabaseCol], Iterable[Tuple[DatabaseCol, ...]]]
    ] = []

    for datatype, cols in groups_of_vars_for_change.items():
        curr_alternatives: List[DatabaseCol] = [DatabaseCol(datatype=datatype)]
        available_alternatives = alternatives.get(datatype)
        if available_alternatives and available_alternatives.alternatives:
            curr_alternatives.extend(available_alternatives.alternatives)
        data_type_permutation_mode = (
            available_alternatives.data_type_permutation_mode
            if available_alternatives
            else PermutationTactics.UNIFORM_PERMUTATION
        )
        variants_w_changes = get_variants_for_specified_col_and_type(
            cols, curr_alternatives, data_type_permutation_mode
        )
        full_info_for_creating_combos.append((datatype, cols, list(variants_w_changes)))

    for datatype, cols in groups_of_vars_not_for_change.items():
        curr_alternatives: List[DatabaseCol] = [DatabaseCol(datatype=datatype)]
        variants_wo_changes = get_variants_for_specified_col_and_type(
            cols, curr_alternatives, PermutationTactics.UNIFORM_PERMUTATION
        )
        full_info_for_creating_combos.append((datatype, cols, list(variants_wo_changes)))

    for combo in itertools.product(*(combo_info[2] for combo_info in full_info_for_creating_combos)):
        curr_ddl_data: Dict[str, DatabaseCol] = {}
        for (_, cols, _), curr_combo in zip(full_info_for_creating_combos, combo):
            for col_curr_data, col_new_data in zip(cols, curr_combo):
                if col_curr_data.name:
                    curr_ddl_data[col_curr_data.name] = col_new_data

        curr_ddl_data_w_tables_in_initial_order = []
        for col in cols_list:
            if col.name in curr_ddl_data:
                new_col_data = curr_ddl_data[col.name]
                curr_ddl_data_w_tables_in_initial_order.append(
                    DatabaseCol(
                        name=col.name,
                        datatype=new_col_data.datatype,
                        codec=new_col_data.codec,
                        other_params=col.other_params,
                    )
                )
        curr_ddl_data_w_tables_in_initial_order.extend(cols_to_append)
        yield curr_ddl_data_w_tables_in_initial_order


def iterate_over_all_indexes_benchmark_variants(
    cols_list: Sequence[str], close_bracket_id: int, str_cols_for_index: List[str]
) -> Iterable[Tuple[List[str], str, IndexType | None]]:
    cols_list_copy = list(cols_list)
    part_a = cols_list_copy[:close_bracket_id]
    part_b = cols_list_copy[close_bracket_id:]

    for params in ngrambf_v1_params:
        if (
            params.n_gram_size == -1
            or params.bloom_filter_size_in_bytes == -1
            or params.num_hashes == -1
            or params.granularity == -1
        ):
            yield [], "", None
        index_params_str = (
            f"ngrambf_v1({params.n_gram_size}, {params.bloom_filter_size_in_bytes}, "
            f"{params.num_hashes}, 0) GRANULARITY {params.granularity}"
        )
        res = list(part_a)
        for col_name in str_cols_for_index:
            full_index_str = f"index idx_{col_name}_test {col_name} type {index_params_str}"
            res = res + [full_index_str]
        res[-1] = res[-1][:-1]
        res = res + part_b
        yield res, index_params_str, IndexType.NGRAMBF_V1


if __name__ == "__main__":
    data_types_to_check: Sequence[DatabaseCol] = tuple(
        [
            DatabaseCol(name="id", datatype="Int64"),
            DatabaseCol(name="data_type", datatype="String"),
            DatabaseCol(name="email", datatype="String"),
            DatabaseCol(name="time", datatype="DateTime('UTC')"),
            DatabaseCol(name="value", datatype="String"),
        ]
    )
    data_types_possible_alternatives: Dict[str, DataTypeAlternatives] = {
        "String": string_alternatives,
    }
    for combo in iterate_over_all_data_compression_variants(
        data_types_to_check, data_types_possible_alternatives
    ):
        combo_w_tables_in_order = []
        for col in data_types_to_check:
            if col.name in combo:
                combo_w_tables_in_order.append(combo[col.name])
    print("done!")