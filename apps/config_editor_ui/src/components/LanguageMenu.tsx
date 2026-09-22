import { useEffect, useRef, useState } from 'react';
import { Button } from '@adqm/gpb-ui';
import { MaterialIcon } from './MaterialIcon';
import { translations, useI18n } from '../i18n';

export function LanguageMenu(): JSX.Element {
  const { locale, setLocale } = useI18n();
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
    <Button ref={trigger} variant="secondary" className="language-indicator" aria-label={`${translations[locale].language.label}: ${locale.toUpperCase()}`} aria-haspopup="menu" aria-expanded={open} aria-controls="language-options" onClick={() => setOpen(!open)}>
      <span className="language-mark"><MaterialIcon name="language" /></span><strong>{locale.toUpperCase()}</strong><MaterialIcon name="chevron_down" />
    </Button>
    {open && <div id="language-options" role="menu" aria-label={translations[locale].language.label} className="workspace-menu-options language-menu-options">
      {(['ru', 'en'] as const).map((item) => <Button key={item} ref={item === locale ? selected : undefined} variant="tertiary" role="menuitemradio" aria-checked={item === locale} className="workspace-menu-option" onClick={() => { setLocale(item); close(); }}><span>{translations[locale].language[item === 'ru' ? 'russian' : 'english']}</span>{item === locale ? <MaterialIcon name="check" /> : null}</Button>)}
    </div>}
  </div>;
}
