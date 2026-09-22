import { request } from '../control/api';

export type StrategyOptionKind = 'source_type' | 'column_type' | 'codec_alternative' | 'skip_index' | 'table_granularity';

export interface StrategyOption {
  id: string;
  kind: StrategyOptionKind;
  canonical_value: string;
  label: string;
  description: string;
  applicability: 'supported' | 'conditional';
  reason_code: string;
  requires_parameters?: boolean;
  parameter_schema?: { name: string; kind: 'integer'; minimum: number; maximum: number; default: number };
  default_granularity?: number;
  integer_value?: number;
}

interface StrategyOptionsResponse { schema_version: 1; catalogue_revision: string; items: StrategyOption[]; next_cursor: null; }

export interface StrategyOptionsInput { kind: StrategyOptionKind; locale: 'ru' | 'en'; query: string; matcherType: string; selected: string[]; signal?: AbortSignal }

export function optionRequestKey({ kind, locale, query, matcherType, selected }: Omit<StrategyOptionsInput, 'signal'>): string {
  return [kind, locale, query.trim().toLowerCase(), matcherType.trim(), [...selected].sort().join(',')].join('|');
}

export function loadStrategyOptions({ kind, locale, query, matcherType, selected, signal }: StrategyOptionsInput): Promise<StrategyOptionsResponse> {
  return request<StrategyOptionsResponse>('/api/v1/strategy-options/suggest', {
    method: 'POST',
    signal,
    body: JSON.stringify({ schema_version: 1, kind, locale, query, ...(matcherType.trim() ? { matcher: { by_type: matcherType.trim() } } : {}), selected, limit: 20 }),
  });
}
