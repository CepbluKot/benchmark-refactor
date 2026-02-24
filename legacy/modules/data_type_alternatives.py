from modules.all_ddl_variants_generator import (
    generate_possible_compressions_w_preprocessings,
    generate_possible_new_datatypes,
)
from modules.interfaces import DataTypeAlternatives, PermutationTactics
timestamp_alternatives = DataTypeAlternatives(
    alternatives=generate_possible_new_datatypes(
        [
            # добавил сюда String, чтобы он прогнался с разными сжатиями (костыль)
            # "Datetime",
            "DateTime64(3)",
        ],
        generate_possible_compressions_w_preprocessings("Datetime"),
    ),
    data_type_permutation_mode=PermutationTactics.UNIFORM_PERMUTATION,
)
string_alternatives = DataTypeAlternatives(
    alternatives=generate_possible_new_datatypes(
        [
            # добавил сюда String, чтобы он прогнался с разными сжатиями (костыль)
            "String",
        ],
        generate_possible_compressions_w_preprocessings("String"),
    ),
    allowed_cols_names=set(["log", "message", "auditID"]),
    data_type_permutation_mode=PermutationTactics.UNIFORM_PERMUTATION,
)
string_alternatives_w_lowcardinality = DataTypeAlternatives(
    alternatives=generate_possible_new_datatypes(
        [
            # добавил сюда String, чтобы он прогнался с разными сжатиями (костыль)
            "String",
            "LowCardinality(String)",
        ],
        generate_possible_compressions_w_preprocessings("String"),
    ),
    data_type_permutation_mode=PermutationTactics.UNIFORM_PERMUTATION,
)
array_string_alternatives = DataTypeAlternatives(
    alternatives=generate_possible_new_datatypes(
        [
            # добавил сюда String, чтобы он прогнался с разными сжатиями (костыль)
            "Array(String)",
            "Array(LowCardinality(String))",
        ],
        generate_possible_compressions_w_preprocessings("String"),
    ),
    data_type_permutation_mode=PermutationTactics.UNIFORM_PERMUTATION,
)
map_string_string_alternatives = DataTypeAlternatives(
    alternatives=generate_possible_new_datatypes(
        [
            # добавил сюда String, чтобы он прогнался с разными сжатиями (костыль)
            "Map(String, String)",
            "Map(String, LowCardinality(String))",
            "Map(LowCardinality(String), String)",
            "Map(LowCardinality(String), LowCardinality(String))",
        ],
        generate_possible_compressions_w_preprocessings("String"),
    ),
    data_type_permutation_mode=PermutationTactics.UNIFORM_PERMUTATION,
)
array_map_string_string_alternatives = DataTypeAlternatives(
    alternatives=generate_possible_new_datatypes(
        [
            # добавил сюда String, чтобы он прогнался с разными сжатиями (костыль)
            "Array(Map(String, String))",
            "Array(Map(String, LowCardinality(String)))",
            "Array(Map(LowCardinality(String), String))",
            "Array(Map(LowCardinality(String), LowCardinality(String)))",
        ],
        generate_possible_compressions_w_preprocessings("String"),
    ),
    data_type_permutation_mode=PermutationTactics.UNIFORM_PERMUTATION,
)
lower_int_dimension_alternatives = DataTypeAlternatives(
    alternatives=generate_possible_new_datatypes(
        ["Int16"],
        generate_possible_compressions_w_preprocessings("Int"),
    ),
    allowed_cols_names=set(["responseStatus_code", "ResponseStatus_code"]),
    data_type_permutation_mode=PermutationTactics.UNIFORM_PERMUTATION,
)