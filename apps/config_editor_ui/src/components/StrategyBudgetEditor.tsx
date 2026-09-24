import { Alert, TextField } from '@adqm/gpb-ui';
import { useI18n } from '../i18n';
import type { StrategyBudgetDraft } from '../strategies/model';
import type { SearchProcedure } from '../strategies/dimensions';
import { MaterialIcon } from './MaterialIcon';

interface StrategyBudgetEditorProps {
  value: StrategyBudgetDraft;
  procedure: SearchProcedure;
  errors: Record<string, string>;
  onChange(next: StrategyBudgetDraft): void;
}

type VisibleBudgetKey = 'rowsPerInsert' | 'insertRepetitions' | 'maxCandidates' | 'topN';

export function StrategyBudgetEditor({ value, procedure, errors, onChange }: StrategyBudgetEditorProps): JSX.Element {
  const { locale, t } = useI18n();
  const formatNumber = (number: number) => number.toLocaleString(locale === 'ru' ? 'ru-RU' : 'en-US');
  const updateNumber = (key: VisibleBudgetKey, raw: string) => onChange({ ...value, [key]: raw === '' ? 0 : Number(raw) });
  const field = (key: VisibleBudgetKey, label: string, help: string) => <div className="strategy-budget-field"><TextField label={label} type="number" step={1} min={1} value={value[key]} error={errors[key]} onChange={(event) => updateNumber(key, event.target.value)} /><p className="field-help">{help}</p></div>;

  return <div className="strategy-budget-editor">
    <section className="strategy-budget-group strategy-budget-group--data" aria-labelledby="strategy-budget-data-title">
      <div className="strategy-budget-group-heading"><span className="strategy-budget-group-icon"><MaterialIcon name="data" size={22} /></span><div><h3 id="strategy-budget-data-title">{t('Данные для INSERT-теста', 'INSERT test data')}</h3><p>{t('Определяет, сколько строк вставлять во временную таблицу кандидата и сколько раз повторить измерение.', 'Controls how many rows are inserted into a candidate’s temporary table and how many times the measurement is repeated.')}</p></div></div>
      <div className="strategy-budget-fields">{field('rowsPerInsert', t('Строк в одном тестовом INSERT', 'Rows in one test INSERT'), t('Размер данных для одного измерения кандидата.', 'Data volume for one candidate measurement.'))}{field('insertRepetitions', t('Повторов INSERT-теста', 'INSERT test repetitions'), t('Повторы снижают влияние случайных колебаний; для оценки используется медиана.', 'Repeats reduce random variation; the median is used for scoring.'))}</div>
      <div className="strategy-budget-explanation"><strong>{t('Как измеряется кандидат', 'How a candidate is measured')}</strong><p>{t(`Для каждого кандидата: ${formatNumber(value.insertRepetitions)} измерения × ${formatNumber(value.rowsPerInsert)} строк.`, `For each candidate: ${formatNumber(value.insertRepetitions)} measurements × ${formatNumber(value.rowsPerInsert)} rows.`)}</p></div>
    </section>
    <section className="strategy-budget-group strategy-budget-group--search" aria-labelledby="strategy-budget-search-title">
      <div className="strategy-budget-group-heading"><span className="strategy-budget-group-icon"><MaterialIcon name="strategy" size={22} /></span><div><h3 id="strategy-budget-search-title">{t('Ограничения поиска', 'Search limits')}</h3><p>{t('Ограничивает число измеряемых вариантов и количество победителей, которые проходят дальше.', 'Limits the number of measured candidates and the winners that continue.')}</p></div></div>
      <div className="strategy-budget-fields">{field('maxCandidates', t('Максимум проверяемых вариантов', 'Maximum candidates to test'), t('Жёсткий предел числа вариантов в одном поиске.', 'Hard limit for candidates in one search.'))}{procedure === 'sequential' ? field('topN', t('Проходит дальше после шага (Top-N)', 'Continue after each step (Top-N)'), t('После каждого направления только лучшие варианты продолжают поиск.', 'After each dimension, only the best candidates continue.')) : null}</div>
      {procedure === 'sequential' ? <div className="strategy-budget-explanation"><strong>{t('Как ограничивается перебор', 'How the search is limited')}</strong><p>{t(`Будет проверено не более ${formatNumber(value.maxCandidates)} вариантов. После каждого направления дальше пройдут Top-${formatNumber(value.topN)}.`, `Up to ${formatNumber(value.maxCandidates)} candidates will be tested. After each dimension, Top-${formatNumber(value.topN)} continue.`)}</p></div> : <Alert tone="info" title={t('Комбинированный поиск', 'Combined search')}>{t(`Будет проверено не более ${formatNumber(value.maxCandidates)} сочетаний. Все результаты сравниваются вместе — промежуточный Top-N не применяется.`, `Up to ${formatNumber(value.maxCandidates)} combinations will be tested. All results are compared together; intermediate Top-N does not apply.`)}</Alert>}
    </section>
  </div>;
}
