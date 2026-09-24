import { useEffect, useId, useRef, useState } from 'react';
import { Button, TextField } from '@adqm/gpb-ui';
import { useI18n } from '../i18n';
import { loadStrategyOptions, type StrategyOption } from '../strategies/options';

export function SourceTypeAutocomplete({ value, onChange, placeholder = 'String' }: { value: string; onChange(value: string): void; placeholder?: string }): JSX.Element {
  const { locale, t } = useI18n();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<StrategyOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState(false);
  const [active, setActive] = useState(0);
  const inputId = useId();
  const listId = `${inputId}-options`;
  const abort = useRef<AbortController | null>(null);
  const kind="source_type";

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setLoading(true); setFailure(false);
      void loadStrategyOptions({ kind, locale, query: value, matcherType: '', selected: [], signal: controller.signal }).then((response) => {
        if (!controller.signal.aborted) { setItems(response.items); setActive(0); }
      }).catch(() => {
        if (!controller.signal.aborted) { setItems([]); setFailure(true); }
      }).finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    }, 200);
    return () => { window.clearTimeout(timer); abort.current?.abort(); };
  }, [kind, locale, open, value]);

  const onSelect = (item: StrategyOption) => { onChange(item.canonical_value); setOpen(false); };

  return <div className="source-type-autocomplete" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <TextField id={inputId} label={t('Исходный тип колонки', 'Source column type')} value={value} placeholder={placeholder} role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={listId} aria-activedescendant={open && items[active] ? `${listId}-${items[active].id}` : undefined} onFocus={() => setOpen(true)} onChange={(event) => { onChange(event.target.value); setOpen(true); }} onKeyDown={(event) => {
      if (event.key === 'ArrowDown' && items.length) { event.preventDefault(); setActive((current) => Math.min(current + 1, items.length - 1)); }
      if (event.key === 'ArrowUp' && items.length) { event.preventDefault(); setActive((current) => Math.max(current - 1, 0)); }
      if (event.key === 'Escape') setOpen(false);
      if (event.key === 'Enter' && items[active]) { event.preventDefault(); onSelect(items[active]); }
    }} />
    {open ? <div id={listId} className="alternative-suggestions source-type-suggestions" role="listbox" aria-label={t('Типы колонок', 'Column types')}>
      <p className="alternative-context">{t('Выберите исходный тип колонки или введите значение вручную.', 'Choose a source column type or enter a value manually.')}</p>
      {loading ? <p>{t('Ищем типы…', 'Finding types…')}</p> : null}
      {!loading && failure ? <p>{t('Не удалось загрузить типы. Можно ввести значение вручную.', 'Could not load types. You can enter a value manually.')}</p> : null}
      {!loading && !failure && !items.length ? <p>{t('Ничего не найдено. Введите значение вручную.', 'No matches. Enter a value manually.')}</p> : null}
      {!loading && !failure ? items.map((item, index) => <Button key={item.id} id={`${listId}-${item.id}`} variant="tertiary" role="option" aria-selected={index === active} className={index === active ? 'is-active' : ''} onMouseDown={(event) => event.preventDefault()} onClick={() => onSelect(item)}><strong>{item.label}</strong><code>{item.canonical_value}</code><small>{item.description}</small></Button>) : null}
    </div> : null}
  </div>;
}
