from itertools import permutations, product
from typing import List, Set, Tuple
from modules.interfaces import DatabaseCol, IndexParams, IndexType

MAX_COMPRESSION_PERMUTATIONS = 1


class Compression:
    def __init__(self, name: str, min_lvl: int = -1, max_lvl: int = -1) -> None:
        self.name = name
        self.min_lvl: int = min_lvl
        self.max_lvl: int = max_lvl


ALL_POSSIBLE_COMPRESSIONS = [
    Compression("ZSTD", 1, 5),  # max lvl = 22
    Compression("LZ4"),
    # Compression("LZ4HC", 1, 3), # max lvl = 12
]

ALL_POSSIBLE_PREPROCESSINGS: Set[str] = {
    "Delta",
    "T64",
    "DoubleDelta",
    "GCD",
    "FPC",
}


def generate_possible_compressions() -> List[str]:
    possible_compressions: List[str] = []
    for compression in ALL_POSSIBLE_COMPRESSIONS:
        if compression.min_lvl == -1:
            possible_compressions.append(compression.name)
            continue
        for compression_lvl in range(compression.min_lvl, compression.max_lvl + 1):
            possible_compressions.append(f"{compression.name}({compression_lvl})")
    return possible_compressions


def generate_permutations(arr: List[str], max_len: int = 2) -> List[Tuple[str, ...]]:
    """Генерирует все перестановки длиной 1..max_len как кортежи."""
    res: List[Tuple[str, ...]] = []
    n = len(arr)
    if n == 0:
        return res
    # длина перестановки не должна превышать ни max_len, ни n
    for r in range(1, min(max_len, n) + 1):
        for p in permutations(arr, r):
            res.append(p)
    return res


def generate_possible_compressions_w_preprocessings(datatype: str) -> List[str]:
    possible_compressions_w_preprocessings: List[str] = []
    possible_compressions = generate_possible_compressions()
    all_possible_preprocessings = set(ALL_POSSIBLE_PREPROCESSINGS)

    # todo: проверить правила для preprocessings
    dt_lower = datatype.lower()
    if "string" in dt_lower:
        # строковым типам большинство предобработок не подходит
        all_possible_preprocessings = set()
    elif "datetime" in dt_lower:
        all_possible_preprocessings = all_possible_preprocessings.difference({"FPC"})
    elif "int" in dt_lower:
        all_possible_preprocessings = all_possible_preprocessings.difference({"FPC"})

    preprocessings_permutations = generate_permutations(
        list(all_possible_preprocessings), MAX_COMPRESSION_PERMUTATIONS
    )

    for compression in possible_compressions:
        possible_compressions_w_preprocessings.append(f"{compression}")
        for perm in preprocessings_permutations:
            possible_compressions_w_preprocessings.append(", ".join(perm) + f", {compression}")

    return possible_compressions_w_preprocessings


def generate_possible_compressions_w_preprocessings_for_one_datatype(
    input_datatype: str, possible_compressions_w_preprocessings: List[str]
) -> List[DatabaseCol]:
    res: List[DatabaseCol] = []
    for compression in possible_compressions_w_preprocessings:
        res.append(DatabaseCol(datatype=input_datatype, codec=compression))
    return res


def generate_possible_new_datatypes(
    new_possible_datatypes: List[str],
    possible_compressions_w_preprocessings: List[str],
) -> List[DatabaseCol]:
    res: List[DatabaseCol] = []
    for new_datatype in new_possible_datatypes:
        possible_compressions_for_type = generate_possible_compressions_w_preprocessings_for_one_datatype(
            new_datatype, possible_compressions_w_preprocessings
        )
        res.extend(possible_compressions_for_type)
    return res


def generate_possible_index_params(
    index_type: IndexType,
    n_gram_possible_sizes: List[int],
    bloom_filter_possible_sizes_in_bytes: List[int],
    num_hashes_possible: List[int],
    granularity_possible: List[int],
) -> List[IndexParams]:
    possible_params: List[IndexParams] = []

    if index_type == IndexType.NGRAMBF_V1:
        for index_params in product(
            n_gram_possible_sizes,
            bloom_filter_possible_sizes_in_bytes,
            num_hashes_possible,
            granularity_possible,
        ):
            possible_params.append(
                IndexParams(
                    n_gram_size=index_params[0],
                    bloom_filter_size_in_bytes=index_params[1],
                    num_hashes=index_params[2],
                    granularity=index_params[3],
                )
            )

    elif index_type == IndexType.TOKENBF_v1:
        for index_params in product(
            bloom_filter_possible_sizes_in_bytes, num_hashes_possible, granularity_possible
        ):
            possible_params.append(
                IndexParams(
                    bloom_filter_size_in_bytes=index_params[0],
                    num_hashes=index_params[1],
                    granularity=index_params[2],
                )
            )

    elif index_type == IndexType.FULL_TEXT:
        possible_params.append(
            IndexParams(additional_settings_at_ddl_end="settings allow_experimental_full_text_index=1")
        )

    return possible_params