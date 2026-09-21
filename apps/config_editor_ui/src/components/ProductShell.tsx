import { useState } from 'react';
import type { ReactNode } from 'react';
import { Button, IconButton, Modal, TextField, ThemeProvider, useThemePreference } from '@adqm/gpb-ui';
import { LanguageMenu } from './LanguageMenu';
import { WorkspaceMenu } from './WorkspaceMenu';
import { WorkspaceAvatarPicker } from './WorkspaceAvatarPicker';
import { type WorkspaceIcon as WorkspaceIconName } from './workspaceIcons';
import { useWorkspace } from '../control/workspace';
import { MaterialIcon, type MaterialIconName } from './MaterialIcon';

export type ProductPage = 'sources' | 'benchmarks' | 'create-benchmark' | 'edit-benchmark' | 'runs' | 'strategies' | 'create-strategy' | 'edit-strategy' | 'design-system';

const NAVIGATION: Array<{ id: Exclude<ProductPage, 'create-benchmark' | 'edit-benchmark' | 'create-strategy' | 'edit-strategy'>; label: string; icon: MaterialIconName }> = [
  { id: 'benchmarks', label: 'Бенчмарки', icon: 'benchmark' },
  { id: 'runs', label: 'Запуски', icon: 'play' },
  { id: 'sources', label: 'Источники данных', icon: 'data' },
  { id: 'strategies', label: 'Стратегии поиска', icon: 'strategy' },
  { id: 'design-system', label: 'Дизайн-система', icon: 'design_services' },
];

export function ProductShell({ page, onPageChange, children }: { page: ProductPage; onPageChange(page: ProductPage): void; children: ReactNode }): JSX.Element {
  const { workspaces, activeWorkspaceId, selectWorkspace, createWorkspace, error, lastSocketEventAt } = useWorkspace();
  const [theme, setTheme] = useThemePreference();
  const [workspaceModal, setWorkspaceModal] = useState(false);
  const [workspaceName, setWorkspaceName] = useState('');
  const [workspaceIcon, setWorkspaceIcon] = useState<WorkspaceIconName>('target');
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const currentPage = page === 'create-benchmark' || page === 'edit-benchmark' ? 'benchmarks' : page === 'create-strategy' || page === 'edit-strategy' ? 'strategies' : page;
  const showWorkspaceSelector = !['strategies', 'create-strategy', 'edit-strategy', 'sources'].includes(page);
  const lastSocketUpdate = lastSocketEventAt ? new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(lastSocketEventAt)) : 'ОЖИДАНИЕ';
  return <ThemeProvider theme={theme} className={`product-root ${theme === 'light' ? 'product-light' : 'product-dark'}`}>
    <div className={`product-frame${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside id="product-navigation" className="product-nav" aria-label="Основные разделы">
        <div className="product-nav-brand"><div className="product-logo" style={{ cursor: 'default' }}><span><MaterialIcon name="workspace" /></span><strong>DB Benchmark</strong></div><IconButton className="sidebar-close" aria-label={sidebarCollapsed ? 'Развернуть боковую панель' : 'Свернуть боковую панель'} title={sidebarCollapsed ? 'Развернуть боковую панель' : 'Свернуть боковую панель'} aria-expanded={!sidebarCollapsed} aria-controls="product-navigation" onClick={() => setSidebarCollapsed(value => !value)}><MaterialIcon name="collapse" size={18} /></IconButton></div>
        <nav className="product-nav-list">{NAVIGATION.map((item) => <button key={item.id} type="button" title={item.label} aria-label={item.label} aria-current={currentPage === item.id ? 'page' : undefined} className={`product-nav-item${currentPage === item.id ? ' active' : ''}`} onClick={() => onPageChange(item.id)}><span className="nav-glyph"><MaterialIcon name={item.icon} /></span><strong>{item.label}</strong></button>)}</nav>
      </aside>
      <main className="product-main">
        <header className="product-header">
          <div className="product-header-start">{showWorkspaceSelector ? <WorkspaceMenu workspaces={workspaces} activeId={activeWorkspaceId} onSelect={selectWorkspace} onCreate={() => setWorkspaceModal(true)} /> : null}</div>
          <div className="product-header-meta"><IconButton className="theme-toggle" aria-label={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'} title={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'} onClick={() => setTheme(theme === 'light' ? 'gpb' : 'light')}><MaterialIcon name={theme === 'light' ? 'dark_mode' : 'light_mode'} /></IconButton><LanguageMenu /><span className={`socket-status${error ? ' socket-status--offline' : ''}`} role="status" aria-live="polite"><MaterialIcon name="settings" size={16} />СОКЕТ: {error ? 'НЕТ СВЯЗИ' : 'ПОДКЛЮЧЕН'}<time dateTime={lastSocketEventAt ?? undefined}>{lastSocketUpdate}</time></span></div>
        </header>
        <div className="product-content">{children}</div>
      </main>
      <Modal open={workspaceModal} onClose={() => setWorkspaceModal(false)} title="Создать пространство" footer={<><Button variant="secondary" onClick={() => setWorkspaceModal(false)}>Отмена</Button><Button variant="primary" disabled={!workspaceName.trim() || creatingWorkspace} onClick={async () => { setCreatingWorkspace(true); try { await createWorkspace(workspaceName, workspaceIcon); setWorkspaceName(''); setWorkspaceIcon('target'); setWorkspaceModal(false); } finally { setCreatingWorkspace(false); } }}>{creatingWorkspace ? 'Создание…' : 'Создать'}</Button></>}>
        <div className="form-stack workspace-create-form">
          <div className="workspace-identity workspace-identity-edit">
            <WorkspaceAvatarPicker value={workspaceIcon} onChange={setWorkspaceIcon} disabled={creatingWorkspace} />
            <div className="workspace-name-input"><TextField label="Название пространства" value={workspaceName} disabled={creatingWorkspace} onChange={(event) => setWorkspaceName(event.target.value)} placeholder="Например, Аналитика витрины" /></div>
          </div>
        </div>
      </Modal>
    </div>
  </ThemeProvider>;
}
