import { useMemo, useState } from 'react';
import { Button, SelectField, TextArea, TextField } from '@adqm/gpb-ui';
import { FORMULA_FUNCTIONS, FORMULA_VARIABLES, SCORING_PRESETS, type ScoringPreset, type StrategyScoringDraft } from '../strategies/model';

export function StrategyScoringEditor({ value, error, onChange }: { value: StrategyScoringDraft; error?: string; onChange(value: StrategyScoringDraft): void }): JSX.Element {
  const [query, setQuery] = useState('');
  const variables = useMemo(() => FORMULA_VARIABLES.filter(([name, description]) => `${name} ${description}`.toLowerCase().includes(query.toLowerCase())), [query]);
  const choosePreset = (preset: ScoringPreset) => onChange({ ...value, preset, formula: SCORING_PRESETS[preset].formula, direction: SCORING_PRESETS[preset].direction });
  return <div className="form-stack strategy-scoring-editor">
    <div className="strategy-subsection-heading"><h3>Formula preset</h3><p>Choose a starting point, then edit the expression if needed.</p></div>
    <div className="strategy-preset-grid">{Object.entries(SCORING_PRESETS).map(([key, preset]) => <Button key={key} variant={value.preset === key ? 'primary' : 'secondary'} aria-pressed={value.preset === key} onClick={() => choosePreset(key as ScoringPreset)}><strong>{preset.title}</strong><small>{preset.description}</small></Button>)}</div>
    <div className="strategy-formula-grid"><div className="form-stack"><TextArea label="Scoring formula" rows={5} value={value.formula} onChange={(event) => onChange({ ...value, preset: 'custom', formula: event.target.value })} /><SelectField label="Direction" value={value.direction} options={[{ value: 'maximize', label: 'Higher score is better' }, { value: 'minimize', label: 'Lower score is better' }]} onChange={(event) => onChange({ ...value, direction: event.target.value as StrategyScoringDraft['direction'] })} />{error ? <p className="field-error" role="alert">{error}</p> : null}<div className="strategy-derived-variables"><strong>Named values</strong><code>read_gain = medians.source_select_time_ms / medians.tested_select_time_ms</code><code>insert_gain = medians.source_insert_time_ms / medians.tested_insert_time_ms</code><code>storage_gain = source_size_bytes / tested_size_bytes</code></div></div>
      <aside className="strategy-variable-catalog"><h3>Variables and functions</h3><TextField label="Search variables" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="read, insert, size…" /><div className="strategy-variable-list">{variables.map(([name, description]) => <Button key={name} variant="tertiary" onClick={() => onChange({ ...value, preset: 'custom', formula: `${value.formula}${value.formula.trim() ? ' ' : ''}${name}` })}><code>{name}</code><small>{description}</small></Button>)}</div><div className="strategy-function-list"><strong>Functions</strong><p>{FORMULA_FUNCTIONS.join(' · ')}</p></div></aside></div>
  </div>;
}
