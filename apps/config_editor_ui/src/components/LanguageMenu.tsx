import { useEffect, useRef, useState } from 'react';
import { Button } from '@adqm/gpb-ui';
import { MaterialIcon } from './MaterialIcon';

export function LanguageMenu(): JSX.Element {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const selected = useRef<HTMLButtonElement>(null);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    selected.current?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  return <div className="language-menu" ref={root} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }} onKeyDown={event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault(); setOpen(true); selected.current?.focus();
    }
  }}>
    <Button ref={trigger} variant="secondary" className="language-indicator" aria-label="Язык интерфейса: русский" aria-haspopup="menu" aria-expanded={open} aria-controls="language-options" onClick={() => setOpen(!open)}>
      <span className="language-mark"><MaterialIcon name="language" /></span><strong>RU</strong><MaterialIcon name="chevron_down" />
    </Button>
    {open && <div id="language-options" role="menu" aria-label="Язык интерфейса" className="workspace-menu-options language-menu-options">
      <Button ref={selected} variant="tertiary" role="menuitemradio" aria-checked="true" className="workspace-menu-option" onClick={close}><span>Русский (RU)</span><MaterialIcon name="check" /></Button>
      <Button variant="tertiary" role="menuitemradio" aria-checked="false" disabled><span>English (EN)<small>Пока недоступен</small></span></Button>
    </div>}
  </div>;
}
