import { useState } from 'react';
import type { ReactNode } from 'react';
import { Button, IconButton, Modal, TextField, ThemeProvider, useThemePreference } from '@adqm/gpb-ui';
import { LanguageMenu } from './LanguageMenu';
import { WorkspaceMenu } from './WorkspaceMenu';
import { WorkspaceAvatarPicker } from './WorkspaceAvatarPicker';
import { type WorkspaceIcon as WorkspaceIconName } from './workspaceIcons';
import { useWorkspace } from '../control/workspace';
import { MaterialIcon, type MaterialIconName } from './MaterialIcon';
import { useI18n } from '../i18n';
import type { ProductPage } from '../navigation-state';

export type { ProductPage } from '../navigation-state';
type NavigationLabel = 'benchmarks' | 'runs' | 'sources' | 'strategies' | 'designSystem';

const NAVIGATION: Array<{ id: Exclude<ProductPage, 'create-benchmark' | 'edit-benchmark' | 'create-strategy' | 'edit-strategy'>; label: NavigationLabel; icon: MaterialIconName }> = [
  { id: 'benchmarks', label: 'benchmarks', icon: 'benchmark' },
  { id: 'runs', label: 'runs', icon: 'play' },
  { id: 'sources', label: 'sources', icon: 'data' },
  { id: 'strategies', label: 'strategies', icon: 'strategy' },
  { id: 'design-system', label: 'designSystem', icon: 'design_services' },
];
function navigationLabel(label: NavigationLabel, t: (ru: string, en: string) => string): string {
  return { benchmarks: t('Бенчмарки', 'Benchmarks'), runs: t('Запуски', 'Runs'), sources: t('Источники данных', 'Data sources'), strategies: t('Стратегии поиска', 'Search strategies'), designSystem: t('Дизайн-система', 'Design system') }[label];
}

export function ProductShell({ page, onPageChange, children }: { page: ProductPage; onPageChange(page: ProductPage): void; children: ReactNode }): JSX.Element {
  const { workspaces, activeWorkspaceId, selectWorkspace, createWorkspace, error, lastSocketEventAt } = useWorkspace();
  const { locale, t } = useI18n();
  const [theme, setTheme] = useThemePreference();
  const [workspaceModal, setWorkspaceModal] = useState(false);
  const [workspaceName, setWorkspaceName] = useState('');
  const [workspaceIcon, setWorkspaceIcon] = useState<WorkspaceIconName>('target');
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const currentPage = page === 'create-benchmark' || page === 'edit-benchmark' ? 'benchmarks' : page === 'create-strategy' || page === 'edit-strategy' ? 'strategies' : page;
  const showWorkspaceSelector = !['strategies', 'create-strategy', 'edit-strategy', 'sources'].includes(page);
  const lastSocketUpdate = lastSocketEventAt ? new Intl.DateTimeFormat(locale === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(lastSocketEventAt)) : t('ОЖИДАНИЕ', 'WAITING');
  return <ThemeProvider theme={theme} className={`product-root ${theme === 'light' ? 'product-light' : 'product-dark'}`}>
    <div className={`product-frame${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside id="product-navigation" className="product-nav" aria-label={t('Основные разделы', 'Primary navigation')}>
        <div className="product-nav-brand"><div className="product-logo" style={{ cursor: 'default' }}><span><MaterialIcon name="data" /></span><strong>DB Benchmark</strong></div><IconButton className="sidebar-close" aria-label={sidebarCollapsed ? t('Развернуть боковую панель', 'Expand sidebar') : t('Свернуть боковую панель', 'Collapse sidebar')} title={sidebarCollapsed ? t('Развернуть боковую панель', 'Expand sidebar') : t('Свернуть боковую панель', 'Collapse sidebar')} aria-expanded={!sidebarCollapsed} aria-controls="product-navigation" onClick={() => setSidebarCollapsed(value => !value)}><MaterialIcon name="collapse" size={18} /></IconButton></div>
        <nav className="product-nav-list">{NAVIGATION.map((item) => { const label = navigationLabel(item.label, t); return <button key={item.id} type="button" title={label} aria-label={label} aria-current={currentPage === item.id ? 'page' : undefined} className={`product-nav-item${currentPage === item.id ? ' active' : ''}`} onClick={() => onPageChange(item.id)}><span className="nav-glyph"><MaterialIcon name={item.icon} /></span><strong>{label}</strong></button>; })}</nav>
      </aside>
      <main className="product-main">
        <header className="product-header">
          <div className="product-header-start">{showWorkspaceSelector ? <WorkspaceMenu workspaces={workspaces} activeId={activeWorkspaceId} onSelect={selectWorkspace} onCreate={() => setWorkspaceModal(true)} /> : null}</div>
          <div className="product-header-meta"><IconButton className="theme-toggle" aria-label={theme === 'light' ? t('Включить тёмную тему', 'Enable dark theme') : t('Включить светлую тему', 'Enable light theme')} title={theme === 'light' ? t('Включить тёмную тему', 'Enable dark theme') : t('Включить светлую тему', 'Enable light theme')} onClick={() => setTheme(theme === 'light' ? 'gpb' : 'light')}><MaterialIcon name={theme === 'light' ? 'dark_mode' : 'light_mode'} /></IconButton><LanguageMenu /><span className={`socket-status${error ? ' socket-status--offline' : ''}`} role="status" aria-live="polite"><MaterialIcon name="settings" size={16} />{t('СОКЕТ:', 'SOCKET:')} {error ? t('НЕТ СВЯЗИ', 'OFFLINE') : t('ПОДКЛЮЧЕН', 'CONNECTED')}<time dateTime={lastSocketEventAt ?? undefined}>{lastSocketUpdate}</time></span></div>
        </header>
        <div className="product-content">{children}</div>
      </main>
      <Modal open={workspaceModal} onClose={() => setWorkspaceModal(false)} title={t('Создать пространство', 'Create workspace')} footer={<><Button variant="secondary" onClick={() => setWorkspaceModal(false)}>{t('Отмена', 'Cancel')}</Button><Button variant="primary" disabled={!workspaceName.trim() || creatingWorkspace} onClick={async () => { setCreatingWorkspace(true); try { await createWorkspace(workspaceName, workspaceIcon); setWorkspaceName(''); setWorkspaceIcon('target'); setWorkspaceModal(false); } finally { setCreatingWorkspace(false); } }}>{creatingWorkspace ? t('Создание…', 'Creating…') : t('Создать', 'Create')}</Button></>}>
        <div className="form-stack workspace-create-form">
          <div className="workspace-identity workspace-identity-edit">
            <WorkspaceAvatarPicker value={workspaceIcon} onChange={setWorkspaceIcon} disabled={creatingWorkspace} />
            <div className="workspace-name-input"><TextField label={t('Название пространства', 'Workspace name')} value={workspaceName} disabled={creatingWorkspace} onChange={(event) => setWorkspaceName(event.target.value)} placeholder={t('Например, Аналитика витрины', 'For example, Warehouse analytics')} /></div>
          </div>
        </div>
      </Modal>
    </div>
  </ThemeProvider>;
}
