import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Switch, TextArea, TextField } from '@adqm/gpb-ui';
import { useWorkspace } from '../control/workspace';
import type { Strategy } from '../control/api';
import { createDefaultStrategyDraft, deriveStrategyPhases, METHOD_LABELS, pruneStrategyDraft, validateStrategyStep, type ScoringPriority, type StrategyDraft, type StrategyMethod } from '../strategies/model';

const STEPS = ['Основное', 'Метод поиска', 'Правила вариантов', 'Бюджет поиска', 'Оценка'];
const METHODS: Array<{ value: StrategyMethod; title: string; description: string }> = [
  { value: 'types_strategy', title: 'Типы и кодеки', description: 'Подбирает физические типы колонок и цепочки кодеков.' },
  { value: 'indexes_strategy', title: 'Skip-индексы', description: 'Ищет подходящие skip-индексы для выбранной таблицы.' },
  { value: 'combined_strategy', title: 'Комбинированный поиск', description: 'Оценивает типы, кодеки и индексы в одном поиске.' },
  { value: 'sequential_topn_strategy', title: 'Последовательный Top-N', description: 'Сначала отбирает лучшие типы и кодеки, затем индексы.' },
  { value: 'sequential_phased_topn_strategy', title: 'Поэтапный Top-N', description: 'Полный поэтапный поиск с ORDER BY и финальной проверкой.' },
];
const PRIORITIES: Array<{ value: ScoringPriority; title: string; description: string }> = [
  { value: 'balanced', title: 'Сбалансированно', description: 'Учитывать чтение, вставку и размер хранения.' },
  { value: 'faster_reads', title: 'Быстрее чтение', description: 'Отдать приоритет времени SELECT-запросов.' },
  { value: 'faster_inserts', title: 'Быстрее вставка', description: 'Сильнее учитывать скорость загрузки данных.' },
  { value: 'better_compression', title: 'Лучше сжатие', description: 'Сильнее учитывать итоговый размер данных.' },
];
const PHASE_LABELS: Record<string, string> = { order_by: 'ORDER BY', types: 'Типы', codecs: 'Кодеки', top_n: 'Top-N', index_granularity: 'Гранулярность', indexes: 'Индексы', final_validation: 'Финальная проверка' };

function numberValue(value: string): number | undefined { return value === '' ? undefined : Number(value); }
function fromStrategy(strategy?: Strategy): StrategyDraft {
  if (!strategy) return createDefaultStrategyDraft();
  const config = strategy.config;
  return {
    name: strategy.name,
    description: strategy.description,
    method: config.method,
    rules: {
      columnTypes: config.rules.column_types ?? false,
      codecs: config.rules.codecs ?? false,
      skipIndexes: config.rules.skip_indexes ?? false,
      tableIndexGranularity: config.rules.table_index_granularity ?? false,
      orderBy: config.rules.order_by ?? false,
      columnOrder: config.rules.column_order ?? false,
    },
    budget: {
      rowsPerInsert: config.budget.rows_per_insert,
      insertRepetitions: config.budget.insert_repetitions,
      maxCandidates: config.budget.max_candidates,
      topN: config.budget.top_n,
      advanced: Object.keys(config.budget).some((key) => !['rows_per_insert', 'insert_repetitions', 'max_candidates', 'top_n'].includes(key)),
      baselineRows: config.budget.baseline_rows,
      candidateRows: config.budget.candidate_rows,
      perPhaseCandidates: config.budget.per_phase_candidates,
      winnersPerParent: config.budget.winners_per_parent,
      finalValidationCandidates: config.budget.final_validation_candidates,
      finalValidationIndexAlternatives: config.budget.final_validation_index_alternatives,
    },
    scoring: {
      priority: config.scoring.priority,
      maxStorageGrowthPercent: config.scoring.max_storage_growth_percent,
      maxInsertSlowdownPercent: config.scoring.max_insert_slowdown_percent,
      minSelectImprovementPercent: config.scoring.min_select_improvement_percent,
    },
  };
}

export function StrategyEditorPage({ strategyId, onCancel, onDone }: { strategyId?: string; onCancel(): void; onDone(): void }): JSX.Element {
  const { strategies, createStrategy, updateStrategy, lastSocketEventAt } = useWorkspace();
  const existing = strategies.find((item) => item.id === strategyId);
  const [draft, setDraft] = useState<StrategyDraft>(() => fromStrategy(existing));
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState<ReturnType<typeof pruneStrategyDraft> | null>(null);
  const [submittedSocketAt, setSubmittedSocketAt] = useState<string | null | undefined>(undefined);
  const initialStrategyIds = useRef(new Set(strategies.map((item) => item.id)));
  const phases = useMemo(() => deriveStrategyPhases(draft.method), [draft.method]);

  useEffect(() => {
    if (!submitted || submittedSocketAt === undefined || lastSocketEventAt === submittedSocketAt) return;
    const match = strategies.find((item) => (strategyId ? item.id === strategyId : !initialStrategyIds.current.has(item.id)) && item.name === submitted.name);
    if (match) onDone();
  }, [lastSocketEventAt, onDone, strategies, strategyId, submitted, submittedSocketAt]);

  const patch = <K extends keyof StrategyDraft>(key: K, value: StrategyDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const next = () => { const found = validateStrategyStep(draft, step); setErrors(found); if (!Object.keys(found).length) setStep((value) => Math.min(4, value + 1)); };
  const submit = async () => {
    const allErrors = { ...validateStrategyStep(draft, 0), ...validateStrategyStep(draft, 3), ...validateStrategyStep(draft, 4) };
    setErrors(allErrors);
    if (Object.keys(allErrors).length || busy) return;
    const payload = pruneStrategyDraft(draft);
    setBusy(true); setFailure(null); setSubmittedSocketAt(lastSocketEventAt); setSubmitted(payload);
    try { if (strategyId) await updateStrategy(strategyId, payload); else await createStrategy(payload); }
    catch (reason) { setSubmitted(null); setBusy(false); setFailure(reason instanceof Error ? reason.message : 'Не удалось сохранить стратегию.'); }
  };

  const ruleSwitch = (key: keyof StrategyDraft['rules'], label: string) => <Switch label={label} checked={draft.rules[key]} onChange={(event) => patch('rules', { ...draft.rules, [key]: event.target.checked })} />;
  const numberField = (key: keyof StrategyDraft['budget'], label: string, help?: string) => <TextField label={label} type="number" min={1} value={draft.budget[key] as number | undefined ?? ''} error={errors[key]} onChange={(event) => patch('budget', { ...draft.budget, [key]: numberValue(event.target.value) })} placeholder={help} />;
  const scoreField = (key: keyof StrategyDraft['scoring'], label: string) => <TextField label={label} type="number" value={draft.scoring[key] as number | undefined ?? ''} error={errors[key]} onChange={(event) => patch('scoring', { ...draft.scoring, [key]: numberValue(event.target.value) })} adornment="%" />;

  return <div className="page-stack product-page strategy-editor-page">
    <div className="page-heading"><div><Button variant="secondary" onClick={onCancel}>← К стратегиям</Button><h1>{strategyId ? 'Редактировать стратегию' : 'Создать стратегию'}</h1><p>Настройте повторно используемый шаблон физического поиска.</p></div></div>
    {failure ? <Alert tone="danger" title="Не удалось сохранить">{failure}</Alert> : null}
    <div className="strategy-editor-layout">
      <nav className="strategy-stepper" aria-label="Этапы создания стратегии">{STEPS.map((label, index) => <Button key={label} variant={index === step ? 'primary' : 'secondary'} aria-current={index === step ? 'step' : undefined} disabled={index > step + 1 || busy} onClick={() => index <= step && setStep(index)}><span>{index + 1}</span>{label}</Button>)}</nav>
      <section className="strategy-editor-card">
        {step === 0 ? <div className="form-stack"><h2>Основное</h2><TextField label="Название" value={draft.name} error={errors.name} onChange={(event) => patch('name', event.target.value)} placeholder="Например, Поэтапная оптимизация витрины" /><TextArea label="Описание" rows={4} maxLength={500} value={draft.description} onChange={(event) => patch('description', event.target.value)} placeholder="Необязательное пояснение для команды" /></div> : null}
        {step === 1 ? <div className="form-stack"><h2>Метод поиска</h2><div className="strategy-choice-grid">{METHODS.map((method) => <Button key={method.value} variant={draft.method === method.value ? 'primary' : 'secondary'} aria-pressed={draft.method === method.value} onClick={() => patch('method', method.value)}><strong>{method.title}</strong><small>{method.description}</small></Button>)}</div><div className="strategy-pipeline"><strong>Этапы поиска</strong><div>{phases.map((phase, index) => <span key={phase}>{index ? '→ ' : ''}{PHASE_LABELS[phase] ?? phase}</span>)}</div></div></div> : null}
        {step === 2 ? <div className="form-stack"><h2>Правила вариантов</h2><p>Включите группы изменений, которые разрешено проверять.</p>{['types_strategy', 'combined_strategy', 'sequential_topn_strategy', 'sequential_phased_topn_strategy'].includes(draft.method) ? <>{ruleSwitch('columnTypes', 'Альтернативные типы колонок')}{ruleSwitch('codecs', 'Альтернативные кодеки')}</> : null}{['indexes_strategy', 'combined_strategy', 'sequential_topn_strategy', 'sequential_phased_topn_strategy'].includes(draft.method) ? ruleSwitch('skipIndexes', 'Типы skip-индексов и их гранулярность') : null}{draft.method === 'sequential_phased_topn_strategy' ? <>{ruleSwitch('tableIndexGranularity', 'Значения index_granularity таблицы')}{ruleSwitch('orderBy', 'Кандидаты ORDER BY')}{ruleSwitch('columnOrder', 'Порядок колонок')}</> : null}</div> : null}
        {step === 3 ? <div className="form-stack"><h2>Бюджет поиска</h2><div className="grid-2">{numberField('rowsPerInsert', 'Строк для одного измерения INSERT')}{numberField('insertRepetitions', 'Повторов измерения INSERT')}{numberField('maxCandidates', 'Максимум кандидатов')}{numberField('topN', 'Победителей Top-N')}</div><Switch label="Расширенные настройки" checked={draft.budget.advanced} onChange={(event) => patch('budget', { ...draft.budget, advanced: event.target.checked })} />{draft.budget.advanced ? <div className="grid-2">{numberField('baselineRows', 'Строк базового варианта')}{numberField('candidateRows', 'Строк варианта-кандидата')}{numberField('perPhaseCandidates', 'Кандидатов на этап')}{numberField('winnersPerParent', 'Победителей на родительский вариант')}{numberField('finalValidationCandidates', 'Вариантов финальной проверки')}{draft.method === 'sequential_phased_topn_strategy' ? numberField('finalValidationIndexAlternatives', 'Альтернатив индекса в финальной проверке') : null}</div> : null}</div> : null}
        {step === 4 ? <div className="form-stack"><h2>Оценка</h2><div className="strategy-choice-grid scoring-grid">{PRIORITIES.map((priority) => <Button key={priority.value} variant={draft.scoring.priority === priority.value ? 'primary' : 'secondary'} aria-pressed={draft.scoring.priority === priority.value} onClick={() => patch('scoring', { ...draft.scoring, priority: priority.value })}><strong>{priority.title}</strong><small>{priority.description}</small></Button>)}</div><h3>Жёсткие ограничения</h3><div className="grid-3">{scoreField('maxStorageGrowthPercent', 'Максимальный рост хранения')}{scoreField('maxInsertSlowdownPercent', 'Максимальное замедление INSERT')}{scoreField('minSelectImprovementPercent', 'Минимальное ускорение SELECT')}</div></div> : null}
        <footer className="strategy-editor-actions"><Button variant="secondary" disabled={busy} onClick={onCancel}>Отмена</Button><div>{step > 0 ? <Button variant="secondary" disabled={busy} onClick={() => setStep((value) => value - 1)}>Назад</Button> : null}{step < 4 ? <Button variant="primary" disabled={busy} onClick={next}>Далее</Button> : <Button variant="primary" disabled={busy} onClick={() => void submit()}>{busy ? 'Сохранение…' : strategyId ? 'Сохранить' : 'Создать стратегию'}</Button>}</div></footer>
      </section>
      <aside className="strategy-summary"><span>Шаблон</span><strong>{draft.name || 'Без названия'}</strong><dl><dt>Метод</dt><dd>{METHOD_LABELS[draft.method]}</dd><dt>Этапов</dt><dd>{phases.length}</dd><dt>Кандидатов</dt><dd>{draft.budget.maxCandidates}</dd><dt>Приоритет</dt><dd>{PRIORITIES.find((item) => item.value === draft.scoring.priority)?.title}</dd></dl></aside>
    </div>
  </div>;
}
