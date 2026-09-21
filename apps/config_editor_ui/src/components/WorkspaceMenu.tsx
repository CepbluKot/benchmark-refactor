import { useEffect, useRef, useState } from 'react';
import { Button } from '@adqm/gpb-ui';
import { WorkspaceIcon } from './WorkspaceIcon';
import { MaterialIcon } from './MaterialIcon';

export function WorkspaceMenu({ workspaces, activeId, onSelect, onCreate }: {
  workspaces: { id: string; name: string; icon: string }[];
  activeId: string;
  onSelect(id: string): void;
  onCreate(): void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    root.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"][aria-checked="true"], [role="menuitem"]')?.focus();
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  return <div className="workspace-menu" ref={root} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }} onKeyDown={(event) => {
    if (!open) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const items = Array.from(root.current!.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]'));
      const current = items.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items[next]?.focus();
    }
  }}>
    <Button ref={trigger} variant="secondary" className="workspace-menu-trigger" aria-haspopup="menu" aria-expanded={open} aria-controls="workspace-options" onClick={() => setOpen(!open)} onKeyDown={(event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setOpen(true); }
    }}>
      <span className="workspace-menu-icon" aria-hidden="true"><WorkspaceIcon icon={workspaces.find((item) => item.id === activeId)?.icon} /></span>
      <span className="workspace-menu-copy"><small>Текущее пространство</small><strong>{workspaces.find(item => item.id === activeId)?.name ?? 'Выберите пространство'}</strong></span>
      <MaterialIcon name="chevron_down" />
    </Button>
    {open && <div id="workspace-options" role="menu" aria-label="Пространства" className="workspace-menu-options">
      <div className="workspace-menu-list">{workspaces.map(item => <Button key={item.id} variant="tertiary" role="menuitemradio" aria-checked={item.id === activeId} className="workspace-menu-option" onClick={() => { onSelect(item.id); close(); }}><span className="workspace-menu-option-label"><span aria-hidden="true"><WorkspaceIcon icon={item.icon} /></span>{item.name}</span>{item.id === activeId ? <MaterialIcon name="check" /> : null}</Button>)}</div>
      <Button variant="tertiary" role="menuitem" className="workspace-menu-create" onClick={() => { close(); onCreate(); }}>Создать пространство</Button>
    </div>}
  </div>;
}
