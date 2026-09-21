import { useState, useRef } from 'react';
import { Button } from '@adqm/gpb-ui';
import { WorkspaceIcon } from './WorkspaceIcon';
import { MaterialIcon } from './MaterialIcon';
import { WORKSPACE_ICON_OPTIONS, type WorkspaceIcon as IconName } from './workspaceIcons';

export function WorkspaceAvatarPicker({ value, onChange, disabled }: { value: IconName; onChange(value: IconName): void; disabled: boolean }): JSX.Element {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return <div className="workspace-avatar-picker" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} onKeyDown={event => { if (event.key === 'Escape' && open) { event.stopPropagation(); setOpen(false); trigger.current?.focus(); } }}>
    <Button ref={trigger} className="workspace-avatar-trigger" variant="primary" disabled={disabled} aria-label="Выбрать иконку пространства" aria-expanded={open} aria-controls="workspace-avatar-options" onClick={() => setOpen(!open)}><WorkspaceIcon icon={value} /><MaterialIcon name="chevron_down" className="workspace-avatar-chevron" /></Button>
    {open && <div id="workspace-avatar-options" className="workspace-avatar-popover workspace-icon-picker" role="group" aria-label="Иконка пространства"><strong>Выберите иконку</strong><div>{WORKSPACE_ICON_OPTIONS.map(item => <Button key={item.value} className="workspace-avatar-choice" variant="secondary" aria-label={item.label} aria-pressed={value === item.value} title={item.label} onClick={() => { onChange(item.value); setOpen(false); trigger.current?.focus(); }}><WorkspaceIcon icon={item.value} />{value === item.value && <MaterialIcon name="check" className="workspace-avatar-check" />}</Button>)}</div></div>}
  </div>;
}
