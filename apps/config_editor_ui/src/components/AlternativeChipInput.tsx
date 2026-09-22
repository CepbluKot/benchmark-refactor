import { useEffect, useId, useRef, useState } from 'react';
import { Button, TextField } from '@adqm/gpb-ui';
import { MaterialIcon } from './MaterialIcon';
import { useI18n } from '../i18n';
import { loadStrategyOptions, type StrategyOptionKind } from '../strategies/options';

export function AlternativeChipInput({ kind, label, matcherType, values, onChange, placeholder, tone, showSuggestions = true }: { kind: StrategyOptionKind; label: string; matcherType: string; values: string[]; onChange(values: string[]): void; placeholder: string; tone: 'types' | 'codecs' | 'indexes' | 'granularity'; showSuggestions?: boolean }): JSX.Element {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Array<{ id: string; canonical_value: string; label: string; description: string; requires_parameters?: boolean; parameter_schema?: { default: number } }>>([]);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState(false);
  const [active, setActive] = useState(0);
  const inputId = useId();
  const listId = `${inputId}-options`;
  const abort = useRef<AbortController | null>(null);
  const add = (value: string) => {
    const normalized = value.trim();
    if (!normalized || values.includes(normalized)) return;
    onChange([...values, normalized]);
    setQuery(''); setOpen(false);
  };
  useEffect(() => {
    if (!open || !showSuggestions) return;
    const timer = window.setTimeout(() => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setLoading(true); setFailure(false);
      void loadStrategyOptions({ kind, locale, query, matcherType, selected: values, signal: controller.signal }).then((response) => {
        if (!controller.signal.aborted) { setItems(response.items); setActive(0); }
      }).catch(() => { if (!controller.signal.aborted) { setItems([]); setFailure(true); } }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { window.clearTimeout(timer); abort.current?.abort(); };
  }, [kind, locale, matcherType, open, query, showSuggestions, values]);
  const choose = (item: { canonical_value: string; requires_parameters?: boolean; parameter_schema?: { default: number } }) => {
    if (item.requires_parameters && item.parameter_schema) { setQuery(item.canonical_value.replace(/\(.*\)$/, `(${item.parameter_schema.default})`)); return; }
    add(item.canonical_value);
  };
  return <div className={`alternative-chip-input alternative-chip-input-${tone}`}>
    <span className="alternative-chip-label">{label}</span>
    {values.length ? <div className="alternative-chip-list">{values.map((value) => <span key={value} className="alternative-chip"><code>{value}</code><Button variant="tertiary" className="strategy-remove" aria-label={`${t('Удалить', 'Remove')} ${value}`} onClick={() => onChange(values.filter((item) => item !== value))}>×</Button></span>)}</div> : null}
    <div className="alternative-picker">
      <TextField id={inputId} label={t('Добавить вариант', 'Add alternative')} value={query} placeholder={placeholder} role="combobox" aria-autocomplete="list" aria-expanded={open && showSuggestions} aria-controls={showSuggestions ? listId : undefined} aria-activedescendant={open && showSuggestions && items[active] ? `${listId}-${items[active].id}` : undefined} onFocus={() => setOpen(showSuggestions)} onChange={(event) => { setQuery(event.target.value); setOpen(showSuggestions); }} onKeyDown={(event) => {
        if (event.key === 'ArrowDown' && items.length) { event.preventDefault(); setActive((value) => Math.min(value + 1, items.length - 1)); }
        if (event.key === 'ArrowUp' && items.length) { event.preventDefault(); setActive((value) => Math.max(value - 1, 0)); }
        if (event.key === 'Escape') { setOpen(false); }
        if (event.key === 'Enter') { event.preventDefault(); if (items[active]) choose(items[active]); else add(query); }
      }} />
      <Button variant="secondary" className="strategy-add" onClick={() => add(query)}><MaterialIcon name="check" size={16} />{t('Добавить', 'Add')}</Button>
      {open && showSuggestions ? <div id={listId} className="alternative-suggestions" role="listbox" aria-label={t('Варианты', 'Alternatives')}>
        <p className="alternative-context">{matcherType ? t(`Для ${matcherType} · Общий каталог`, `For ${matcherType} · Generic catalogue`) : t('Общий каталог · проверьте применимость при запуске', 'Generic catalogue · applicability is checked at run time')}</p>
        {loading ? <p>{t('Ищем варианты…', 'Finding alternatives…')}</p> : null}
        {!loading && failure ? <p>{t('Не удалось загрузить варианты. Можно ввести вручную.', 'Could not load options. You can enter a value manually.')}</p> : null}
        {!loading && !failure && !items.length ? <p>{t('Ничего не найдено. Введите значение вручную.', 'No matches. Enter a value manually.')}</p> : null}
        {!loading && !failure ? items.map((item, index) => <Button key={item.id} id={`${listId}-${item.id}`} variant="tertiary" role="option" aria-selected={index === active} className={index === active ? 'is-active' : ''} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(item)}><strong>{item.label}</strong><code>{item.canonical_value}</code><small>{item.description}</small></Button>) : null}
      </div> : null}
    </div>
  </div>;
}
