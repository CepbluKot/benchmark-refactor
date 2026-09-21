export type SearchProcedure = 'combined' | 'sequential' | 'phased';
export interface AlternativeRule {
  by_type: string;
  by_name?: string;
  alternatives: string[];
}
export interface IndexAlternative { type: string; granularity: number }
export interface IndexRule { by_type: string; by_name?: string; indexes: IndexAlternative[] }
export interface SearchDimensions {
  column_types: AlternativeRule[];
  codecs: AlternativeRule[];
  skip_indexes: IndexRule[];
  order_by: { first_column?: string; candidates: string[] };
  column_order: Array<{ column: string; position: number }>;
  table_index_granularity_values: number[];
}
export function emptyDimensions(): SearchDimensions {
  return { column_types: [], codecs: [], skip_indexes: [], order_by: { candidates: [] }, column_order: [], table_index_granularity_values: [] };
}
export function validateDimensions(d: SearchDimensions): string | undefined {
  const positive = (n: number) => Number.isInteger(n) && n > 0;
  for (const rule of [...d.column_types, ...d.codecs]) {
    if (!rule.by_type.trim() || !rule.alternatives.length || rule.alternatives.some(value => !value.trim())) return 'Для каждого правила задайте исходный тип и хотя бы одну альтернативу.';
  }
  for (const rule of d.skip_indexes) {
    if (!rule.by_type.trim() || !rule.indexes.length || rule.indexes.some(index => !index.type.trim() || !positive(index.granularity))) return 'Для индекса задайте исходный тип, тип индекса и целую гранулярность больше нуля.';
  }
  if (d.table_index_granularity_values.some(n => !positive(n))) return 'Гранулярность таблицы: только целые числа больше нуля.';
  if (d.column_order.some(row => !row.column.trim() || !positive(row.position))) return 'Для порядка колонок задайте имя и целую позицию больше нуля.';
  if (new Set(d.column_order.map(row => row.column.trim())).size !== d.column_order.length || new Set(d.column_order.map(row => row.position)).size !== d.column_order.length) return 'Имена и позиции колонок должны быть уникальными.';
  if (!d.column_types.length && !d.codecs.length && !d.skip_indexes.length && !d.order_by.candidates.length && !d.column_order.length && !d.table_index_granularity_values.length) return 'Настройте хотя бы одно направление оптимизации.';
  return undefined;
}
export function dimensionPhases(d: SearchDimensions, procedure: SearchProcedure): string[] {
  const phases = [
    ...(d.order_by.candidates.length ? ['order_by'] : []),
    ...(d.column_types.length ? ['types'] : []),
    ...(d.codecs.length ? ['codecs'] : []),
    ...(d.column_order.length ? ['column_order'] : []),
    ...(d.table_index_granularity_values.length ? ['index_granularity'] : []),
    ...(d.skip_indexes.length ? ['indexes'] : []),
  ];
  return [...phases, ...(procedure === 'sequential' ? ['top_n'] : procedure === 'phased' ? ['final_validation'] : [])];
}
