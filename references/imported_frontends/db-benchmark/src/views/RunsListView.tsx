import React, { useState } from 'react';
import {
  PlayCircle,
  Clock,
  ArrowUpRight,
  Search,
  Filter,
  Layers,
  Database,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
} from 'lucide-react';
import { useBenchmark } from '../context/BenchmarkContext';
import { RunStatus } from '../types';
import { Button, StatusBadge } from '../components/ui/GpbComponents';

export const RunsListView: React.FC = () => {
  const { currentWorkspaceRuns, setActiveRunId, setCurrentTab, workspaces, activeWorkspaceId } =
    useBenchmark();

  const currentWorkspace = workspaces.find((w) => w.id === activeWorkspaceId);

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const filteredRuns = currentWorkspaceRuns.filter((r) => {
    const matchesSearch =
      r.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.benchmarkName.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === 'all' || r.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const handleOpenRun = (runId: string) => {
    setActiveRunId(runId);
    setCurrentTab('run-detail');
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Запуски
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            История физических выполнений бенчмарков в пространстве{' '}
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              «{currentWorkspace?.name}»
            </span>
          </p>
        </div>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="p-3 bg-white dark:bg-[#171D26] rounded border border-slate-200 dark:border-[#242C38] flex flex-col md:flex-row items-center justify-between gap-3 shadow-2xs">
        <div className="flex items-center gap-2 w-full md:w-auto flex-1">
          <div className="relative w-full max-w-sm">
            <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Поиск по ID запуска или названию бенчмарка..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-[#1A212C] text-slate-900 dark:text-slate-100 border border-slate-300 dark:border-[#333C4B] rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0]"
            />
          </div>

          <div className="w-40 shrink-0">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full px-2.5 py-1.5 text-xs bg-slate-50 dark:bg-[#1A212C] text-slate-900 dark:text-slate-100 border border-slate-300 dark:border-[#333C4B] rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0]"
            >
              <option value="all">Все состояния</option>
              <option value="running">Выполняется</option>
              <option value="completed">Завершён</option>
              <option value="error">Ошибка</option>
            </select>
          </div>
        </div>

        <div className="text-xs text-slate-500 dark:text-slate-400">
          Всего запусков: <span className="font-semibold">{currentWorkspaceRuns.length}</span>
        </div>
      </div>

      {/* Runs Table */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded overflow-hidden shadow-2xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-[#242C38] bg-slate-50 dark:bg-[#1C232E] text-slate-500 dark:text-slate-400 font-semibold uppercase tracking-wider text-[11px]">
                <th className="px-4 py-3">Запуск</th>
                <th className="px-4 py-3">Бенчмарк</th>
                <th className="px-4 py-3">Время начала</th>
                <th className="px-4 py-3">Текущий этап</th>
                <th className="px-4 py-3">Состояние</th>
                <th className="px-4 py-3 text-right">Действие</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-[#242C38]">
              {filteredRuns.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-slate-400 dark:text-slate-500">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <PlayCircle className="w-8 h-8 stroke-1 text-slate-400" />
                      <p className="font-medium text-sm">Запусков в этом пространстве не найдено</p>
                      <p className="text-xs">
                        Перейдите на страницу «Бенчмарки» и нажмите кнопку «Запустить».
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                filteredRuns.map((run) => {
                  return (
                    <tr
                      key={run.id}
                      onClick={() => handleOpenRun(run.id)}
                      className="hover:bg-slate-50 dark:hover:bg-[#1F2733] transition-colors cursor-pointer"
                    >
                      {/* Run ID */}
                      <td className="px-4 py-3 font-mono font-semibold text-slate-900 dark:text-slate-100">
                        {run.id}
                      </td>

                      {/* Benchmark Name */}
                      <td className="px-4 py-3 font-medium text-slate-800 dark:text-slate-200">
                        {run.benchmarkName}
                      </td>

                      {/* Start Time */}
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-400 font-mono text-[11px]">
                        {run.startedAt}
                      </td>

                      {/* Current Phase */}
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                        <span className="truncate max-w-xs block">{run.currentPhase}</span>
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3">
                        {run.status === 'running' && (
                          <StatusBadge status="running" label="Выполняется" />
                        )}
                        {run.status === 'completed' && (
                          <StatusBadge status="completed" label="Завершён" />
                        )}
                        {run.status === 'error' && <StatusBadge status="error" label="Ошибка" />}
                      </td>

                      {/* Action: Open */}
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenRun(run.id);
                          }}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-[#0033A0] dark:text-[#78A9FF] hover:underline cursor-pointer"
                        >
                          <span>Открыть</span>
                          <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
