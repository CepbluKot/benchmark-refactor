import React, { useState } from 'react';
import {
  ArrowLeft,
  Clock,
  Database,
  Terminal,
  AlertCircle,
  CheckCircle2,
  Copy,
  Layers,
  FileText,
  Activity,
  Server,
  Info,
} from 'lucide-react';
import { useBenchmark } from '../context/BenchmarkContext';
import { StatusBadge, Button, NoticeBanner } from '../components/ui/GpbComponents';

export const RunDetailView: React.FC = () => {
  const { activeRunId, getRunById, setCurrentTab } = useBenchmark();
  const [activeTab, setActiveTab] = useState<'overview' | 'diagnostics'>('overview');

  const run = activeRunId ? getRunById(activeRunId) : null;

  if (!run) {
    return (
      <div className="p-8 text-center space-y-3">
        <p className="text-sm text-slate-500 dark:text-slate-400">Запуск не найден или не выбран.</p>
        <Button onClick={() => setCurrentTab('runs')}>Вернуться к списку запусков</Button>
      </div>
    );
  }

  const isCompleted = run.status === 'completed';
  const isRunning = run.status === 'running';
  const isError = run.status === 'error';

  return (
    <div className="space-y-5 max-w-5xl mx-auto">
      {/* Back button */}
      <div>
        <button
          onClick={() => setCurrentTab('runs')}
          className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:text-slate-100 transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Назад к списку запусков</span>
        </button>
      </div>

      {/* Run Header Card */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-5 shadow-2xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-mono font-bold text-slate-900 dark:text-slate-100">
                Запуск {run.id}
              </h1>
              {isRunning && <StatusBadge status="running" label="Выполняется" />}
              {isCompleted && <StatusBadge status="completed" label="Завершён" />}
              {isError && <StatusBadge status="error" label="Ошибка" />}
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Бенчмарк:{' '}
              <span className="font-semibold text-slate-700 dark:text-slate-300">
                {run.benchmarkName}
              </span>
            </p>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono text-slate-600 dark:text-slate-400">
            <div>
              <span className="text-slate-400 block text-[10px]">Старт</span>
              <span>{run.startedAt}</span>
            </div>
            {run.finishedAt && (
              <div>
                <span className="text-slate-400 block text-[10px]">Завершение</span>
                <span>{run.finishedAt}</span>
              </div>
            )}
          </div>
        </div>

        {/* Phase & Progress Indicator */}
        <div className="pt-3 border-t border-slate-100 dark:border-[#242C38] space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-500 dark:text-slate-400">
              Текущий этап: <strong className="text-slate-800 dark:text-slate-200">{run.currentPhase}</strong>
            </span>
            {isRunning && (
              <span className="text-[11px] font-medium text-[#0033A0] dark:text-[#78A9FF]">
                Условный индикатор прогресса ({run.progressPercent}%)
              </span>
            )}
          </div>

          {/* Progress Bar with honest disclaimer (Section 10) */}
          <div className="w-full bg-slate-100 dark:bg-[#202734] h-2 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                isCompleted
                  ? 'bg-emerald-600'
                  : isError
                  ? 'bg-rose-500'
                  : 'bg-[#0F62FE] animate-pulse'
              }`}
              style={{ width: `${run.progressPercent}%` }}
            />
          </div>

          {isRunning && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500">
              * Примечание: Для выполняющегося запуска отображается условное фиксированное значение.
              Это не измеренный процент готовности эксперимента (согласно разделу 10 спецификации).
            </p>
          )}
        </div>
      </div>

      {/* Metric Cards: Source Rows vs Copy Rows */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
        {/* Source Rows */}
        <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded p-4 shadow-2xs">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Строк в источнике
          </div>
          <div className="mt-2 text-2xl font-mono font-bold text-slate-900 dark:text-slate-100">
            {run.sourceRows > 0 ? run.sourceRows.toLocaleString() : '—'}
          </div>
          <div className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
            COUNT(*) в исходной таблице
          </div>
        </div>

        {/* Copy Rows in Sandbox */}
        <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded p-4 shadow-2xs">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Строк в созданной копии
          </div>
          <div className="mt-2 text-2xl font-mono font-bold text-slate-900 dark:text-slate-100">
            {run.copyRows > 0 ? run.copyRows.toLocaleString() : '—'}
          </div>
          <div className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
            COUNT(*) в таблице sandbox
          </div>
        </div>

        {/* Sandbox Target Table */}
        <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded p-4 shadow-2xs">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Таблица в sandbox
          </div>
          <div className="mt-2 text-xs font-mono font-semibold text-slate-900 dark:text-slate-100 truncate">
            {run.sandboxTableCreated}
          </div>
          <div className="mt-1 text-[11px] text-slate-400 dark:text-slate-500 truncate">
            Изолированная физическая копия
          </div>
        </div>
      </div>

      {/* Error Banner if applicable */}
      {run.errorMessage && (
        <NoticeBanner type="error" title="Сбой выполнения запуска">
          <p className="font-mono text-[11px] mt-1 text-rose-800 dark:text-rose-200 break-words">
            {run.errorMessage}
          </p>
        </NoticeBanner>
      )}

      {/* Detail Tabs: Overview & Diagnostics */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md shadow-2xs overflow-hidden">
        {/* Tab Headers */}
        <div className="flex items-center border-b border-slate-200 dark:border-[#242C38] bg-slate-50 dark:bg-[#1A212D] px-4">
          <button
            onClick={() => setActiveTab('overview')}
            className={`flex items-center gap-2 py-3 px-3 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
              activeTab === 'overview'
                ? 'border-[#0033A0] dark:border-[#0F62FE] text-[#0033A0] dark:text-[#78A9FF] font-semibold'
                : 'border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            <span>Обзор выполнения</span>
          </button>

          <button
            onClick={() => setActiveTab('diagnostics')}
            className={`flex items-center gap-2 py-3 px-3 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
              activeTab === 'diagnostics'
                ? 'border-[#0033A0] dark:border-[#0F62FE] text-[#0033A0] dark:text-[#78A9FF] font-semibold'
                : 'border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Диагностика и события ({run.logs.length})</span>
          </button>
        </div>

        {/* Tab Body */}
        <div className="p-5">
          {activeTab === 'overview' && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div className="space-y-3">
                  <h3 className="font-bold text-slate-900 dark:text-slate-100 text-xs uppercase tracking-wider text-slate-400">
                    Параметры эксперимента
                  </h3>
                  <div className="space-y-1.5 border border-slate-200 dark:border-[#2A3442] rounded p-3 bg-slate-50/50 dark:bg-[#18202A]">
                    <div className="flex justify-between py-1 border-b border-slate-100 dark:border-[#263140]">
                      <span className="text-slate-500">ID запуска:</span>
                      <span className="font-mono font-medium">{run.id}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-100 dark:border-[#263140]">
                      <span className="text-slate-500">Бенчмарк:</span>
                      <span className="font-medium">{run.benchmarkName}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-100 dark:border-[#263140]">
                      <span className="text-slate-500">Целевая таблица sandbox:</span>
                      <span className="font-mono text-[11px] truncate max-w-[200px]">
                        {run.sandboxTableCreated}
                      </span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span className="text-slate-500">Статус верификации:</span>
                      <span>
                        {run.sourceRows > 0 && run.sourceRows === run.copyRows ? (
                          <span className="text-emerald-600 dark:text-emerald-400 font-medium">
                            Строки перенесены ({run.sourceRows.toLocaleString()})
                          </span>
                        ) : run.status === 'running' ? (
                          <span className="text-blue-600 dark:text-blue-400">В процессе копирования</span>
                        ) : (
                          <span className="text-rose-600">Копирование не завершено</span>
                        )}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  <h3 className="font-bold text-slate-900 dark:text-slate-100 text-xs uppercase tracking-wider text-slate-400">
                    Фактическое поведение бэкенда
                  </h3>
                  <NoticeBanner type="info" title="Согласованная архитектурная рамка (Раздел 13)">
                    Текущий обработчик выполняет физическую операцию: считает строки источника,
                    создаёт одну копию таблицы в sandbox, переносит данные и считает строки копии.
                    Ранжирование десятков кандидатов, вычисление ускорения запросов и DDL итоговой
                    рекомендации запланированы в целевом ядре оркестрации.
                  </NoticeBanner>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'diagnostics' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>Журнал физических событий ClickHouse и FastAPI Control API:</span>
                <span className="font-mono text-[11px]">stream: stdout / JSON-RPC</span>
              </div>

              {/* Terminal Log Console */}
              <div className="bg-[#0D1117] text-slate-200 font-mono text-[11px] p-4 rounded-md border border-slate-800 space-y-2 max-h-96 overflow-y-auto leading-relaxed select-text">
                {run.logs.map((log, index) => {
                  const levelColor = {
                    INFO: 'text-blue-400',
                    WARN: 'text-amber-400',
                    ERROR: 'text-rose-400',
                  }[log.level];

                  return (
                    <div key={index} className="flex items-start gap-2.5">
                      <span className="text-slate-500 shrink-0 select-none">[{log.timestamp}]</span>
                      <span className={`font-semibold shrink-0 select-none ${levelColor}`}>
                        {log.level}
                      </span>
                      <div className="min-w-0">
                        <span className="text-slate-200">{log.message}</span>
                        {log.details && (
                          <div className="mt-1 text-[10px] text-slate-400 bg-slate-900/80 p-1.5 rounded border border-slate-800">
                            {log.details}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
