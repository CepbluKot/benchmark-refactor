import React, { useState } from 'react';
import {
  Gauge,
  PlayCircle,
  Database,
  Layers,
  Palette,
  Plus,
  Sun,
  Moon,
  ChevronDown,
  Server,
  Radio,
  Sliders,
  Terminal,
} from 'lucide-react';
import { useBenchmark } from '../../context/BenchmarkContext';
import { NavigationTab } from '../../types';
import { Button, Modal, Input } from '../ui/GpbComponents';

export const Shell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const {
    currentTab,
    setCurrentTab,
    workspaces,
    activeWorkspaceId,
    setActiveWorkspaceId,
    createWorkspace,
    isDark,
    toggleTheme,
    wsConnected,
    lastEventCursor,
    reconnectWs,
    toastMessage,
  } = useBenchmark();

  // Create Workspace Modal
  const [isCreateWsOpen, setIsCreateWsOpen] = useState(false);
  const [newWsName, setNewWsName] = useState('');
  const [newWsDesc, setNewWsDesc] = useState('');
  const [isWsDropdownOpen, setIsWsDropdownOpen] = useState(false);

  const activeWs = workspaces.find((w) => w.id === activeWorkspaceId) || workspaces[0];

  const handleCreateWorkspace = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWsName.trim()) return;
    createWorkspace(newWsName.trim(), newWsDesc.trim() || undefined);
    setNewWsName('');
    setNewWsDesc('');
    setIsCreateWsOpen(false);
  };

  const navItems: { id: NavigationTab; label: string; icon: React.FC<{ className?: string }> }[] = [
    { id: 'benchmarks', label: 'Бенчмарки', icon: Gauge },
    { id: 'runs', label: 'Запуски', icon: PlayCircle },
    { id: 'data-sources', label: 'Источники данных', icon: Database },
    { id: 'strategies', label: 'Стратегии поиска', icon: Layers },
    { id: 'design-system', label: 'Дизайн-система', icon: Palette },
  ];

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#F4F6F9] dark:bg-[#12161D] text-slate-900 dark:text-slate-100 antialiased font-sans">
      {/* Toast alert */}
      {toastMessage && (
        <div className="fixed bottom-4 right-4 z-50 px-4 py-2.5 bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 rounded shadow-lg text-xs font-medium border border-slate-700 dark:border-slate-300 animate-in fade-in slide-in-from-bottom-2">
          {toastMessage}
        </div>
      )}

      {/* Persistent Left Sidebar Menu */}
      <aside className="w-60 shrink-0 border-r border-slate-200 dark:border-[#222A36] bg-white dark:bg-[#171D26] flex flex-col justify-between select-none">
        <div>
          {/* App Header / Brand */}
          <div className="h-14 px-4 flex items-center gap-3 border-b border-slate-200 dark:border-[#222A36]">
            <div className="w-8 h-8 rounded bg-[#0033A0] flex items-center justify-center text-white font-bold text-sm tracking-tight shadow-xs">
              DB
            </div>
            <div className="flex flex-col">
              <span className="font-semibold text-sm leading-tight tracking-tight text-slate-900 dark:text-slate-100">
                DB Benchmark
              </span>
              <span className="text-[11px] text-slate-500 dark:text-slate-400 leading-tight">
                ClickHouse Optimizer
              </span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="p-3 space-y-1">
            <div className="px-2 py-1 text-[10px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
              Рабочие разделы
            </div>
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive =
                currentTab === item.id ||
                (item.id === 'benchmarks' &&
                  (currentTab === 'benchmark-create' || currentTab === 'benchmark-edit')) ||
                (item.id === 'runs' && currentTab === 'run-detail');

              return (
                <button
                  key={item.id}
                  id={`nav-${item.id}`}
                  onClick={() => setCurrentTab(item.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded text-xs font-medium transition-colors cursor-pointer text-left ${
                    isActive
                      ? 'bg-[#0033A0]/10 dark:bg-[#0F62FE]/20 text-[#0033A0] dark:text-[#78A9FF] font-semibold'
                      : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-[#202733]'
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-[#0033A0] dark:text-[#78A9FF]' : 'text-slate-500 dark:text-slate-400'}`} />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Sidebar Footer: Engine & WebSocket Diagnostic Info */}
        <div className="p-3 border-t border-slate-200 dark:border-[#222A36] space-y-2 bg-slate-50/50 dark:bg-[#151A22]">
          <div className="flex items-center justify-between text-[11px] text-slate-600 dark:text-slate-400">
            <span className="flex items-center gap-1.5">
              <Server className="w-3 h-3 text-slate-400" />
              <span>FastAPI API: v1</span>
            </span>
            <span className="font-mono text-[10px] bg-slate-200 dark:bg-slate-800 px-1.5 py-0.5 rounded">
              ClickHouse
            </span>
          </div>

          <div className="flex items-center justify-between text-[11px]">
            <span className="flex items-center gap-1.5 text-slate-600 dark:text-slate-400">
              <Radio
                className={`w-3 h-3 ${
                  wsConnected ? 'text-emerald-500' : 'text-rose-500 animate-pulse'
                }`}
              />
              <span className="truncate">WS: events?after={lastEventCursor}</span>
            </span>
            {!wsConnected ? (
              <button
                onClick={reconnectWs}
                className="text-[10px] text-blue-600 dark:text-blue-400 underline hover:no-underline"
              >
                Обновить
              </button>
            ) : (
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-mono">
                online
              </span>
            )}
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Bar */}
        <header className="h-14 px-6 border-b border-slate-200 dark:border-[#222A36] bg-white dark:bg-[#171D26] flex items-center justify-between shrink-0 select-none">
          {/* Workspace Switcher & Action */}
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
              Пространство:
            </span>

            {/* Workspace Dropdown */}
            <div className="relative">
              <button
                id="workspace-switcher-btn"
                onClick={() => setIsWsDropdownOpen((prev) => !prev)}
                className="flex items-center gap-2 h-8 px-3 rounded border border-slate-300 dark:border-[#333C4B] bg-white dark:bg-[#1D242F] text-xs font-semibold text-slate-800 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-[#252E3C] transition-colors cursor-pointer"
              >
                <span>{activeWs?.name || 'Выберите пространство'}</span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
              </button>

              {isWsDropdownOpen && (
                <>
                  <div
                    className="fixed inset-0 z-20"
                    onClick={() => setIsWsDropdownOpen(false)}
                  />
                  <div className="absolute left-0 top-9 mt-1 w-64 rounded-md shadow-lg border border-slate-200 dark:border-[#333C4B] bg-white dark:bg-[#1A212C] z-30 py-1">
                    <div className="px-3 py-1.5 text-[11px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                      Доступные пространства
                    </div>
                    {workspaces.map((ws) => (
                      <button
                        key={ws.id}
                        onClick={() => {
                          setActiveWorkspaceId(ws.id);
                          setIsWsDropdownOpen(false);
                        }}
                        className={`w-full px-3 py-2 text-left text-xs flex flex-col hover:bg-slate-100 dark:hover:bg-[#26303F] cursor-pointer ${
                          ws.id === activeWorkspaceId
                            ? 'bg-[#0033A0]/10 dark:bg-[#0F62FE]/20 text-[#0033A0] dark:text-[#78A9FF] font-semibold'
                            : 'text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        <span>{ws.name}</span>
                        {ws.description && (
                          <span className="text-[10px] text-slate-400 dark:text-slate-500 truncate">
                            {ws.description}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

            {/* Create Workspace Action */}
            <Button
              id="create-workspace-btn"
              size="sm"
              variant="secondary"
              icon={Plus}
              onClick={() => setIsCreateWsOpen(true)}
            >
              Создать пространство
            </Button>
          </div>

          {/* Right Header Actions */}
          <div className="flex items-center gap-2.5">
            {/* Minimalist Theme Switcher in compact square outline without visible words (Section 5) */}
            <button
              id="theme-toggle-btn"
              onClick={toggleTheme}
              aria-label={isDark ? 'Переключить на светлую тему' : 'Переключить на тёмную тему'}
              title={isDark ? 'Переключить на светлую тему' : 'Переключить на тёмную тему'}
              className="w-8 h-8 rounded border border-slate-300 dark:border-[#333C4B] bg-white dark:bg-[#1D242F] text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-[#252E3C] flex items-center justify-center transition-colors cursor-pointer focus:outline-none focus:ring-1 focus:ring-[#0033A0]"
            >
              {isDark ? (
                <Sun className="w-4 h-4 text-amber-400" />
              ) : (
                <Moon className="w-4 h-4 text-slate-600" />
              )}
            </button>
          </div>
        </header>

        {/* Dynamic Body Content */}
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>

      {/* Modal: Create Workspace */}
      <Modal
        isOpen={isCreateWsOpen}
        onClose={() => setIsCreateWsOpen(false)}
        title="Создание рабочего пространства"
        subtitle="Пространство объединяет связанные бенчмарки и историю их выполнения"
        footer={
          <>
            <Button variant="ghost" onClick={() => setIsCreateWsOpen(false)}>
              Отмена
            </Button>
            <Button variant="primary" onClick={handleCreateWorkspace} disabled={!newWsName.trim()}>
              Создать
            </Button>
          </>
        }
      >
        <form onSubmit={handleCreateWorkspace} className="space-y-3.5">
          <Input
            id="ws-name-input"
            label="Название пространства"
            required
            placeholder="Например: Аналитика продаж или Телеметрия ядра"
            value={newWsName}
            onChange={(e) => setNewWsName(e.target.value)}
          />
          <Input
            id="ws-desc-input"
            label="Описание (необязательно)"
            placeholder="Краткое назначение экспериментов в этом пространстве"
            value={newWsDesc}
            onChange={(e) => setNewWsDesc(e.target.value)}
          />
          <div className="p-3 bg-slate-50 dark:bg-[#1A212C] border border-slate-200 dark:border-[#2C3542] rounded text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
            Пространство является организационной группировкой бенчмарков. Источники данных и шаблоны
            стратегий остаются общими для всей системы.
          </div>
        </form>
      </Modal>
    </div>
  );
};
