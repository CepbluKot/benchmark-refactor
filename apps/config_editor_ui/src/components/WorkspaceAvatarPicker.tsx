import { useState, useRef } from 'react';
import { Button } from '@adqm/gpb-ui';
import { WorkspaceIcon } from './WorkspaceIcon';
import { MaterialIcon } from './MaterialIcon';
import { WORKSPACE_ICON_OPTIONS, type WorkspaceIcon as IconName } from './workspaceIcons';
import { useI18n } from '../i18n';

export function WorkspaceAvatarPicker({ value, onChange, disabled }: { value: IconName; onChange(value: IconName): void; disabled: boolean }): JSX.Element {
  const { t } = useI18n();
  const iconLabels: Record<IconName, string> = {
    target: t('Контур', 'Scope'),
    analytics: t('Аналитика', 'Analytics'),
    data: t('Данные', 'Data'),
    experiment: t('Эксперимент', 'Experiment'),
    operations: t('Операции', 'Operations'),
  };
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return <div className="workspace-avatar-picker" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} onKeyDown={event => { if (event.key === 'Escape' && open) { event.stopPropagation(); setOpen(false); trigger.current?.focus(); } }}>
    <Button ref={trigger} className="workspace-avatar-trigger" variant="primary" disabled={disabled} aria-label={t('Выбрать иконку пространства', 'Choose workspace icon')} aria-expanded={open} aria-controls="workspace-avatar-options" onClick={() => setOpen(!open)}><WorkspaceIcon icon={value} /><MaterialIcon name="chevron_down" className="workspace-avatar-chevron" /></Button>
    {open && <div id="workspace-avatar-options" className="workspace-avatar-popover workspace-icon-picker" role="group" aria-label={t('Иконка пространства', 'Workspace icon')}><strong>{t('Выберите иконку', 'Choose an icon')}</strong><div>{WORKSPACE_ICON_OPTIONS.map(item => <Button key={item.value} className="workspace-avatar-choice" variant="secondary" aria-label={iconLabels[item.value]} aria-pressed={value === item.value} title={iconLabels[item.value]} onClick={() => { onChange(item.value); setOpen(false); trigger.current?.focus(); }}><WorkspaceIcon icon={item.value} />{value === item.value && <MaterialIcon name="check" className="workspace-avatar-check" />}</Button>)}</div></div>}
  </div>;
}
