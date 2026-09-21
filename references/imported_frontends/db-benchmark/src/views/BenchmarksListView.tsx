import React, { useState, useMemo } from 'react';
import {
  Plus,
  Play,
  Settings,
  ArrowUpRight,
  Search,
  Filter,
  Layers,
  CheckCircle2,
  AlertCircle,
  Clock,
  Database,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { useBenchmark } from '../context/BenchmarkContext';
import { BenchmarkReadiness } from '../types';
import { Button, StatusBadge, Input, Select } from '../components/ui/GpbComponents';

export const BenchmarksListView: React.FC = () => {
  const {
    currentWorkspaceBenchmarks,
    workspaces,
    activeWorkspaceId,
    dataSources,
    setCurrentTab,
    setEditingBenchmarkId,
    setActiveRunId,
    triggerRun,
    strategies,
  } = useBenchmark();

  const currentWorkspace = workspaces.find((w) => w.id === activeWorkspaceId);

  // Search & Filter State
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStrategyFilter, setSelectedStrategyFilter] = useState<string>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 6;

  // Filtered benchmarks
  const filteredBenchmarks = useMemo(() => {
    return currentWorkspaceBenchmarks.filter((b) => {
      const matchesSearch =
        b.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        b.sourceTable.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesStrategy =
        selectedStrategyFilter === 'all' || b.strategyTemplateId === selectedStrategyFilter;
      return matchesSearch && matchesStrategy;
    });
  }, [currentWorkspaceBenchmarks, searchQuery, selectedStrategyFilter]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filteredBenchmarks.length / itemsPerPage));
  const paginatedBenchmarks = filteredBenchmarks.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  const getSourceDisplayName = (sourceId: string) => {
    const src = dataSources.find((s) => s.id === sourceId);
    return src ? src.name : sourceId;
  };

  const handleLaunch = async (e: React.MouseEvent, benchmarkId: string) => {
    e.stopPropagation();
    const runId = await triggerRun(benchmarkId);
    setActiveRunId(runId);
    setCurrentTab('run-detail');
  };

  const handleOpenSettings = (e: React.MouseEvent, benchmarkId: string) => {
    e.stopPropagation();
    setEditingBenchmarkId(benchmarkId);
    setCurrentTab('benchmark-edit');
  };

  const handleGoToLastRun = (e: React.MouseEvent, runId?: string) => {
    e.stopPropagation();
    if (!runId) return;
    setActiveRunId(runId);
    setCurrentTab('run-detail');
  };

  return (
    <div className="space-y-5">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Бенчмарки
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Эксперименты над физической структурой таблиц ClickHouse в пространстве{' '}
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              «{currentWorkspace?.name}»
            </span>
          </p>
        </div>

        <Button
          id="create-benchmark-btn"
          variant="primary"
          icon={Plus}
          onClick={() => setCurrentTab('benchmark-create')}
        >
          Создать бенчмарк
        </Button>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="p-3 bg-white dark:bg-[#171D26] rounded border border-slate-200 dark:border-[#242C38] flex flex-col md:flex-row items-center justify-between gap-3 shadow-2xs">
        <div className="flex-1 w-full md:w-auto flex items-center gap-2">
          <div className="relative w-full max-w-sm">
            <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Поиск по названию или база.таблица..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-[#1A212C] text-slate-900 dark:text-slate-100 border border-slate-300 dark:border-[#333C4B] rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0]"
            />
          </div>

          <div className="w-48 shrink-0">
            <select
              value={selectedStrategyFilter}
              onChange={(e) => {
                setSelectedStrategyFilter(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full px-2.5 py-1.5 text-xs bg-slate-50 dark:bg-[#1A212C] text-slate-900 dark:text-slate-100 border border-slate-300 dark:border-[#333C4B] rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0]"
            >
              <option value="all">Все стратегии</option>
              {strategies.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="text-xs text-slate-500 dark:text-slate-400 shrink-0">
          Всего в пространстве: <span className="font-semibold">{currentWorkspaceBenchmarks.length}</span>
        </div>
      </div>

      {/* Main Benchmarks Table */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded overflow-hidden shadow-2xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-[#242C38] bg-slate-50 dark:bg-[#1C232E] text-slate-500 dark:text-slate-400 font-semibold uppercase tracking-wider text-[11px]">
                <th className="px-4 py-3">Название</th>
                <th className="px-4 py-3">Исходная таблица</th>
                <th className="px-4 py-3">Источник</th>
                <th className="px-4 py-3">Стратегия</th>
                <th className="px-4 py-3">Последний запуск</th>
                <th className="px-4 py-3">Готовность</th>
                <th className="px-4 py-3 text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-[#242C38]">
              {paginatedBenchmarks.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-slate-400 dark:text-slate-500">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <Layers className="w-8 h-8 stroke-1 text-slate-400" />
                      <p className="font-medium text-sm">В этом пространстве пока нет бенчмарков</p>
                      <p className="text-xs max-w-sm">
                        Нажмите кнопку «Создать бенчмарк», выберите исходную таблицу ClickHouse и
                        настройте стратегию поиска.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                paginatedBenchmarks.map((bench) => {
                  return (
                    <tr
                      key={bench.id}
                      className="hover:bg-slate-50 dark:hover:bg-[#1F2733] transition-colors"
                    >
                      {/* Name */}
                      <td className="px-4 py-3 font-semibold text-slate-900 dark:text-slate-100">
                        <div className="flex items-center gap-2">
                          <span>{bench.name}</span>
                        </div>
                      </td>

                      {/* Source Table (database.table) */}
                      <td className="px-4 py-3">
                        <span className="font-mono text-[11px] bg-slate-100 dark:bg-[#202733] px-2 py-0.5 rounded text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-[#303B4A]">
                          {bench.sourceTable}
                        </span>
                      </td>

                      {/* Data Source */}
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                        <div className="flex items-center gap-1.5 truncate max-w-[160px]">
                          <Database className="w-3.5 h-3.5 shrink-0 text-slate-400" />
                          <span className="truncate">{getSourceDisplayName(bench.sourceId)}</span>
                        </div>
                      </td>

                      {/* Strategy (Friendly name!) */}
                      <td className="px-4 py-3">
                        <span className="font-medium text-slate-800 dark:text-slate-200">
                          {bench.strategyName}
                        </span>
                      </td>

                      {/* Last Run Status & Link */}
                      <td className="px-4 py-3">
                        {bench.lastRunId ? (
                          <div className="flex items-center gap-2">
                            {bench.lastRunStatus === 'running' && (
                              <StatusBadge status="running" label="Выполняется" />
                            )}
                            {bench.lastRunStatus === 'completed' && (
                              <StatusBadge status="completed" label="Завершён" />
                            )}
                            {bench.lastRunStatus === 'error' && (
                              <StatusBadge status="error" label="Ошибка" />
                            )}
                            <button
                              onClick={(e) => handleGoToLastRun(e, bench.lastRunId)}
                              className="text-[11px] text-[#0033A0] dark:text-[#78A9FF] hover:underline inline-flex items-center gap-0.5 cursor-pointer"
                              title="Перейти к подробностям запуска"
                            >
                              <span>{bench.lastRunId}</span>
                              <ArrowUpRight className="w-3 h-3" />
                            </button>
                          </div>
                        ) : (
                          <span className="text-slate-400 dark:text-slate-500 italic text-[11px]">
                            Не запускался
                          </span>
                        )}
                      </td>

                      {/* Configuration Readiness vs Run Result (Section 6) */}
                      <td className="px-4 py-3">
                        {bench.readinessStatus === 'ready' && (
                          <StatusBadge status="ready" label="Готов к запуску" />
                        )}
                        {bench.readinessStatus === 'source_not_verified' && (
                          <StatusBadge status="not_checked" label="Источник не проверен" />
                        )}
                        {bench.readinessStatus === 'incomplete' && (
                          <StatusBadge status="incomplete" label="Не настроен" />
                        )}
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          <Button
                            size="sm"
                            variant="primary"
                            icon={Play}
                            onClick={(e) => handleLaunch(e, bench.id)}
                            title="Запустить эксперимент на sandbox-копии"
                          >
                            Запустить
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            icon={Settings}
                            onClick={(e) => handleOpenSettings(e, bench.id)}
                            title="Настройки бенчмарка"
                          >
                            Настройки
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        {filteredBenchmarks.length > 0 && (
          <div className="px-4 py-2.5 bg-slate-50 dark:bg-[#1C232E] border-t border-slate-200 dark:border-[#242C38] flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <div>
              Показано {paginatedBenchmarks.length} из {filteredBenchmarks.length} бенчмарков
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={currentPage === 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                className="p-1 rounded border border-slate-200 dark:border-[#333C4B] bg-white dark:bg-[#171D26] disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100 dark:hover:bg-[#202733] cursor-pointer"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="font-medium text-slate-700 dark:text-slate-300">
                {currentPage} / {totalPages}
              </span>
              <button
                disabled={currentPage === totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                className="p-1 rounded border border-slate-200 dark:border-[#333C4B] bg-white dark:bg-[#171D26] disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100 dark:hover:bg-[#202733] cursor-pointer"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
