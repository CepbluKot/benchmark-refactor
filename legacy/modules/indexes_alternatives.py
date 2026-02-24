from modules.all_ddl_variants_generator import (
    generate_possible_index_params,
)
from modules.interfaces import IndexType
from settings import settings
# index idx_log_test log type ngrambf_v1(4, 16384, 3, 0)
# tokenbf_v1(16384, 3, 0)
# index idx_log_test log type full_text  + settings allow_experimental_full_text_index=1; (at the very end)
ngrambf_v1_params = generate_possible_index_params(
    IndexType.NGRAMBF_V1,
    settings.N_GRAM_POSSIBLE_SIZES,
    settings.BLOOM_FILTER_POSSIBLE_SIZES_IN_BYTES,
    settings.NUM_HASHES_POSSIBLE,
    settings.GRANULARITY_POSSIBLE,
)