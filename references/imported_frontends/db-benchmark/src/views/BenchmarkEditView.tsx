import React, { useState, useEffect } from 'react';
import { ArrowLeft, Save, Database, Trash2 } from 'lucide-react';
import { useBenchmark } from '../context/BenchmarkContext';
import { Button, Input, Select, NoticeBanner } from '../components/ui/GpbComponents';

export const BenchmarkEditView: React.FC = () => {
  const {
    editingBenchmarkId,
    getBenchmarkById,
    updateBenchmark,
    setCurrentTab,
    dataSources,
    strategies,
    getTablesForSource,
    workspaces,
    activeWorkspaceId,
  } = useBenchmark();

  const benchmark = editingBenchmarkId ? getBenchmarkById(editingBenchmarkId) : null;
  const currentWorkspace = workspaces.find((w) => w.id === activeWorkspaceId);

  const [name, setName] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [sourceTable, setSourceTable] = useState('');
  const [sandboxDb, setSandboxDb] = useState('');
  const [strategyTemplateId, setStrategyTemplateId] = useState('');

  useEffect(() => {
    if (benchmark) {
      setName(benchmark.name);
      setSourceId(benchmark.sourceId);
      setSourceTable(benchmark.sourceTable);
      setSandboxDb(benchmark.sandboxDatabase);
      setStrategyTemplateId(benchmark.strategyTemplateId);
    }
  }, [benchmark]);

  if (!benchmark) {
    return (
      <div className="p-8 text-center space-y-3">
        <p className="text-sm text-slate-500 dark:text-slate-400">Бенчмарк не найден или не выбран.</p>
        <Button onClick={() => setCurrentTab('benchmarks')}>Вернуться к списку</Button>
      </div>
    );
  }

  const availableTables = getTablesForSource(sourceId);
  const selectedStrategy = strategies.find((s) => s.id === strategyTemplateId);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !sourceTable.trim() || !sandboxDb.trim()) return;

    updateBenchmark(benchmark.id, {
      name: name.trim(),
      sourceId,
      sourceTable: sourceTable.trim(),
      sandboxDatabase: sandboxDb.trim(),
      strategyTemplateId,
      strategyName: selectedStrategy ? selectedStrategy.name : benchmark.strategyName,
    });

    setCurrentTab('benchmarks');
  };

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      {/* Back button */}
      <div>
        <button
          onClick={() => setCurrentTab('benchmarks')}
          className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:text-slate-100 transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Назад к списку бенчмарков</span>
        </button>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Редактирование бенчмарка
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Изменение параметров эксперимента для таблицы{' '}
            <span className="font-mono text-slate-700 dark:text-slate-300">
              {benchmark.sourceTable}
            </span>
          </p>
        </div>

        <div className="text-xs text-slate-400 dark:text-slate-500 font-mono">
          ID: {benchmark.id}
        </div>
      </div>

      {/* Unified Form (Single Page, per section 7) */}
      <form
        onSubmit={handleSave}
        className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-6 shadow-2xs space-y-5"
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <Input
              label="Название бенчмарка"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div>
            <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
              Пространство
            </label>
            <div className="mt-1 px-3 py-1.5 bg-slate-50 dark:bg-[#1C232E] border border-slate-200 dark:border-[#333C4B] rounded text-xs text-slate-700 dark:text-slate-300">
              {currentWorkspace?.name}
            </div>
          </div>

          <div>
            <Select
              label="Источник данных ClickHouse"
              required
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
            >
              {dataSources.map((ds) => (
                <option key={ds.id} value={ds.id}>
                  {ds.name} ({ds.status === 'ready' ? 'Готов' : 'Не проверен'})
                </option>
              ))}
            </Select>
          </div>

          <div>
            <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
              Исходная таблица (база.таблица) <span className="text-rose-500">*</span>
            </label>
            {availableTables.length > 0 ? (
              <select
                value={sourceTable}
                onChange={(e) => setSourceTable(e.target.value)}
                className="mt-1 w-full px-3 py-1.5 text-sm font-mono bg-white dark:bg-[#1C2129] text-slate-900 dark:text-slate-100 border border-slate-300 dark:border-[#343D4B] rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0]"
              >
                {availableTables.map((tbl) => (
                  <option key={tbl} value={tbl}>
                    {tbl}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                value={sourceTable}
                onChange={(e) => setSourceTable(e.target.value)}
                className="font-mono mt-1"
              />
            )}
          </div>

          <div>
            <Input
              label="Тестовая база (Sandbox)"
              required
              value={sandboxDb}
              onChange={(e) => setSandboxDb(e.target.value)}
            />
          </div>

          <div className="md:col-span-2">
            <Select
              label="Шаблон стратегии поиска"
              required
              value={strategyTemplateId}
              onChange={(e) => setStrategyTemplateId(e.target.value)}
            >
              {strategies.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.name} ({st.technicalType})
                </option>
              ))}
            </Select>
          </div>
        </div>

        {selectedStrategy && (
          <div className="p-3 bg-slate-50 dark:bg-[#1A212D] border border-slate-200 dark:border-[#2C3644] rounded text-xs space-y-1.5">
            <div className="font-semibold text-slate-800 dark:text-slate-200">
              Этапы выбранной стратегии:
            </div>
            <div className="flex flex-wrap gap-1">
              {selectedStrategy.phases.map((p, idx) => (
                <span
                  key={idx}
                  className="bg-white dark:bg-[#202734] px-2 py-0.5 rounded border border-slate-200 dark:border-[#303B4A] text-[11px]"
                >
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}

        <NoticeBanner type="info">
          Сохранение бенчмарка и запуск — отдельные действия (согласно п. 11 спецификации).
          После сохранения вы можете инициировать новый эксперимент из таблицы бенчмарков.
        </NoticeBanner>

        <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-[#242C38]">
          <Button variant="ghost" onClick={() => setCurrentTab('benchmarks')}>
            Отмена
          </Button>

          <Button type="submit" variant="primary" icon={Save}>
            Сохранить изменения
          </Button>
        </div>
      </form>
    </div>
  );
};
