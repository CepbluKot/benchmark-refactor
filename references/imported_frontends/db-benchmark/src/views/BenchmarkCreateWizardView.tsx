import React, { useState, useEffect } from 'react';
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Database,
  Layers,
  Settings,
  Sliders,
  Sparkles,
  Info,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import { useBenchmark } from '../context/BenchmarkContext';
import { Button, Input, Select, NoticeBanner } from '../components/ui/GpbComponents';

export const BenchmarkCreateWizardView: React.FC = () => {
  const {
    workspaces,
    activeWorkspaceId,
    dataSources,
    strategies,
    getTablesForSource,
    createBenchmark,
    setCurrentTab,
    preselectedStrategyId,
    setPreselectedStrategyId,
  } = useBenchmark();

  const currentWorkspace = workspaces.find((w) => w.id === activeWorkspaceId);

  // Wizard Step State (1, 2, 3)
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3>(1);

  // Form Fields
  const [benchmarkName, setBenchmarkName] = useState('');
  const [selectedSourceId, setSelectedSourceId] = useState<string>(
    dataSources[0]?.id || ''
  );
  const [selectedTable, setSelectedTable] = useState<string>('');
  const [sandboxDb, setSandboxDb] = useState<string>('sandbox_benchmarks');
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>(
    preselectedStrategyId || strategies[0]?.id || ''
  );

  // Optional future blocks toggle for viewing the design roadmap (honestly marked as preview)
  const [showFutureBlocks, setShowFutureBlocks] = useState(false);
  const [allowedTypes, setAllowedTypes] = useState('LowCardinality(String), UInt32, Int64, DateTime64(3)');
  const [allowedCodecs, setAllowedCodecs] = useState('ZSTD(1), ZSTD(3), DoubleDelta, T64, LZ4HC');
  const [allowedOrderBy, setAllowedOrderBy] = useState('created_at, user_id, event_type');
  const [timeBudget, setTimeBudget] = useState('30');
  const [maxCandidates, setMaxCandidates] = useState('8');

  // Load tables whenever source changes
  const availableTables = getTablesForSource(selectedSourceId);

  useEffect(() => {
    if (availableTables.length > 0 && (!selectedTable || !availableTables.includes(selectedTable))) {
      setSelectedTable(availableTables[0]);
    }
  }, [selectedSourceId, availableTables]);

  useEffect(() => {
    if (preselectedStrategyId) {
      setSelectedStrategyId(preselectedStrategyId);
      // Clean up after consuming
      setPreselectedStrategyId(null);
    }
  }, [preselectedStrategyId]);

  const selectedStrategy = strategies.find((s) => s.id === selectedStrategyId);
  const selectedSource = dataSources.find((s) => s.id === selectedSourceId);

  // Validation
  const isStep1Valid = benchmarkName.trim().length > 0;
  const isStep2Valid = selectedSourceId && selectedTable && sandboxDb.trim().length > 0;
  const isStep3Valid = !!selectedStrategyId;

  const handleFinish = () => {
    if (!isStep1Valid || !isStep2Valid || !isStep3Valid) return;

    createBenchmark({
      workspaceId: activeWorkspaceId,
      name: benchmarkName.trim(),
      sourceId: selectedSourceId,
      sourceTable: selectedTable,
      sandboxDatabase: sandboxDb.trim(),
      strategyTemplateId: selectedStrategyId,
      strategyName: selectedStrategy ? selectedStrategy.name : 'Пользовательская стратегия',
      rulesConfig: showFutureBlocks
        ? {
            allowedTypes: allowedTypes.split(',').map((s) => s.trim()),
            allowedCodecs: allowedCodecs.split(',').map((s) => s.trim()),
            allowedOrderBy: allowedOrderBy.split(',').map((s) => s.trim()),
            indexGranularity: 8192,
          }
        : undefined,
      workloadConfig: showFutureBlocks
        ? {
            timeBudgetMinutes: parseInt(timeBudget) || 30,
            maxCandidates: parseInt(maxCandidates) || 8,
          }
        : undefined,
    });

    setCurrentTab('benchmarks');
  };

  const steps = [
    { num: 1, title: 'Основное', desc: 'Название и пространство' },
    { num: 2, title: 'Источник и таблица', desc: 'Подключение, таблица и sandbox' },
    { num: 3, title: 'Стратегия поиска', desc: 'Выбор шаблона оптимизации' },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Top Breadcrumb / Back Button */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setCurrentTab('benchmarks')}
          className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Назад к списку бенчмарков</span>
        </button>
      </div>

      {/* View Title */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          Создание бенчмарка
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Пошаговая настройка эксперимента над физической структурой таблицы в пространстве{' '}
          <span className="font-semibold text-slate-700 dark:text-slate-300">
            «{currentWorkspace?.name}»
          </span>
        </p>
      </div>

      {/* Stepper Progress Bar */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-4 shadow-2xs">
        <div className="grid grid-cols-3 gap-2">
          {steps.map((s) => {
            const isCompleted = s.num < currentStep;
            const isCurrent = s.num === currentStep;

            return (
              <div
                key={s.num}
                onClick={() => {
                  if (s.num === 1) setCurrentStep(1);
                  if (s.num === 2 && isStep1Valid) setCurrentStep(2);
                  if (s.num === 3 && isStep1Valid && isStep2Valid) setCurrentStep(3);
                }}
                className={`flex items-center gap-3 p-2.5 rounded transition-all select-none ${
                  isCurrent
                    ? 'bg-[#0033A0]/5 dark:bg-[#0F62FE]/15 border border-[#0033A0]/30 dark:border-[#0F62FE]/30'
                    : 'border border-transparent hover:bg-slate-50 dark:hover:bg-[#1F2733]'
                } ${s.num <= currentStep ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}
              >
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center font-bold text-xs shrink-0 ${
                    isCompleted
                      ? 'bg-emerald-600 text-white'
                      : isCurrent
                      ? 'bg-[#0033A0] text-white'
                      : 'bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                  }`}
                >
                  {isCompleted ? <Check className="w-3.5 h-3.5" /> : s.num}
                </div>
                <div className="min-w-0">
                  <div
                    className={`text-xs font-semibold leading-tight truncate ${
                      isCurrent
                        ? 'text-[#0033A0] dark:text-[#78A9FF]'
                        : 'text-slate-800 dark:text-slate-200'
                    }`}
                  >
                    {s.title}
                  </div>
                  <div className="text-[10px] text-slate-400 dark:text-slate-500 leading-tight truncate mt-0.5">
                    {s.desc}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Step Content Container */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-6 shadow-2xs space-y-6">
        {/* STEP 1: Main info */}
        {currentStep === 1 && (
          <div className="space-y-4 max-w-xl">
            <div className="border-b border-slate-200 dark:border-[#242C38] pb-3">
              <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                Шаг 1: Основные сведения
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Задайте понятное название эксперимента. Идентификаторы формируются системой автоматически.
              </p>
            </div>

            <Input
              id="benchmark-name"
              label="Понятное название бенчмарка"
              required
              placeholder="Например: Оптимизация ключа сортировки и сжатия events_v2"
              value={benchmarkName}
              onChange={(e) => setBenchmarkName(e.target.value)}
              helperText="Название будет отображаться в списке бенчмарков и журналах запусков."
            />

            <div>
              <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
                Текущее рабочее пространство
              </label>
              <div className="mt-1 px-3 py-2 bg-slate-50 dark:bg-[#1C232E] border border-slate-200 dark:border-[#333C4B] rounded text-xs font-medium text-slate-800 dark:text-slate-200 flex items-center justify-between">
                <span>{currentWorkspace?.name}</span>
                <span className="text-[11px] text-slate-400">
                  {currentWorkspace?.id}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-1">
                Бенчмарк создаётся внутри текущего выбранного пространства.
              </p>
            </div>
          </div>
        )}

        {/* STEP 2: Data Source & Table */}
        {currentStep === 2 && (
          <div className="space-y-4 max-w-xl">
            <div className="border-b border-slate-200 dark:border-[#242C38] pb-3">
              <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                Шаг 2: Источник данных и таблица
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Выберите подключение к ClickHouse, исходную таблицу для замера и изолированную базу
                sandbox.
              </p>
            </div>

            {/* Source select */}
            <Select
              id="source-selector"
              label="Источник данных (ClickHouse)"
              required
              value={selectedSourceId}
              onChange={(e) => setSelectedSourceId(e.target.value)}
              helperText={
                selectedSource?.status !== 'ready'
                  ? 'Внимание: этот источник ещё не подтверждён проверкой доступности.'
                  : 'Подключение проверено и доступно для чтения схемы.'
              }
            >
              {dataSources.map((ds) => (
                <option key={ds.id} value={ds.id}>
                  {ds.name} ({ds.host}:{ds.port}) —{' '}
                  {ds.status === 'ready'
                    ? 'Готов'
                    : ds.status === 'unavailable'
                    ? 'Недоступен'
                    : 'Не проверен'}
                </option>
              ))}
            </Select>

            {/* Source Table format: database.table */}
            <div>
              <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
                Исходная таблица (формат база.таблица) <span className="text-rose-500">*</span>
              </label>
              {availableTables.length > 0 ? (
                <select
                  value={selectedTable}
                  onChange={(e) => setSelectedTable(e.target.value)}
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
                  placeholder="analytics.events_v2"
                  value={selectedTable}
                  onChange={(e) => setSelectedTable(e.target.value)}
                  className="font-mono"
                />
              )}
              <span className="text-[11px] text-slate-400 dark:text-slate-500 block mt-1">
                Список таблиц запрашивается у ClickHouse backend через GET /api/v1/sources/:id/tables.
              </span>
            </div>

            {/* Sandbox DB */}
            <Input
              id="sandbox-db"
              label="Тестовая база (Sandbox)"
              required
              placeholder="sandbox_benchmarks"
              value={sandboxDb}
              onChange={(e) => setSandboxDb(e.target.value)}
              helperText="Изолированная среда в ClickHouse, в которой разрешено создавать и измерять варианты таблиц."
            />

            <NoticeBanner type="info" title="Архитектурное ограничение">
              Система не модифицирует исходную производственную таблицу. Все замеры и создание
              кандидатов происходят исключительно в выделенной тестовой базе.
            </NoticeBanner>
          </div>
        )}

        {/* STEP 3: Search Strategy */}
        {currentStep === 3 && (
          <div className="space-y-4">
            <div className="border-b border-slate-200 dark:border-[#242C38] pb-3">
              <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                Шаг 3: Выбор стратегии поиска
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Выберите базовый шаблон стратегии. Шаблон определяет последовательность фаз перебора
                структуры.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              {strategies.map((strat) => {
                const isSelected = strat.id === selectedStrategyId;

                return (
                  <div
                    key={strat.id}
                    onClick={() => setSelectedStrategyId(strat.id)}
                    className={`p-4 rounded border transition-all cursor-pointer flex flex-col justify-between ${
                      isSelected
                        ? 'bg-[#0033A0]/5 dark:bg-[#0F62FE]/15 border-[#0033A0] dark:border-[#0F62FE] ring-1 ring-[#0033A0]'
                        : 'bg-white dark:bg-[#19202B] border-slate-200 dark:border-[#2E3746] hover:border-slate-300 dark:hover:border-slate-600'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-sm text-slate-900 dark:text-slate-100">
                          {strat.name}
                        </span>
                        {isSelected && (
                          <span className="w-5 h-5 rounded-full bg-[#0033A0] text-white flex items-center justify-center">
                            <Check className="w-3 h-3" />
                          </span>
                        )}
                      </div>

                      <div className="mt-1 font-mono text-[11px] text-slate-400 dark:text-slate-500">
                        {strat.technicalType}
                      </div>

                      <p className="mt-2 text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                        {strat.description}
                      </p>
                    </div>

                    <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-[#263140]">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-1.5">
                        Фазы стратегии ({strat.phases.length}):
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {strat.phases.map((phase, idx) => (
                          <span
                            key={idx}
                            className="text-[10px] bg-slate-100 dark:bg-[#202734] text-slate-700 dark:text-slate-300 px-1.5 py-0.5 rounded border border-slate-200 dark:border-[#2F3947]"
                          >
                            {idx + 1}. {phase}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Future Blocks Preview Accordion (Honest UI Roadmap) */}
            <div className="mt-6 pt-4 border-t border-slate-200 dark:border-[#242C38]">
              <button
                type="button"
                onClick={() => setShowFutureBlocks((prev) => !prev)}
                className="flex items-center justify-between w-full text-left text-xs font-semibold text-slate-700 dark:text-slate-300 hover:text-[#0033A0] dark:hover:text-blue-400 cursor-pointer"
              >
                <span className="flex items-center gap-1.5">
                  <Sliders className="w-3.5 h-3.5 text-slate-500" />
                  <span>
                    Дополнительно: «Правила вариантов» и «Нагрузка и оценка» (Целевая модель)
                  </span>
                </span>
                <span className="text-[11px] font-normal text-slate-400 underline">
                  {showFutureBlocks ? 'Скрыть блоки' : 'Показать блоки целевой модели'}
                </span>
              </button>

              {showFutureBlocks && (
                <div className="mt-3 p-4 bg-slate-50 dark:bg-[#1A212D] border border-slate-200 dark:border-[#2C3644] rounded space-y-4">
                  <NoticeBanner type="warning" title="Статус реализации (Раздел 7 спецификации)">
                    Эти расширенные блоки согласованы для целевого развития продукта. В текущей
                    интеграционной связке бэкенда запуск копирует данные таблицы в sandbox и
                    подсчитывает строки, а расширенные правила пока сохраняются как конфигурационные
                    параметры.
                  </NoticeBanner>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Block: Правила вариантов */}
                    <div className="space-y-2.5">
                      <div className="text-xs font-bold text-slate-800 dark:text-slate-200">
                        Блок «Правила вариантов»
                      </div>
                      <Input
                        label="Разрешённые типы колонок"
                        value={allowedTypes}
                        onChange={(e) => setAllowedTypes(e.target.value)}
                        placeholder="LowCardinality(String), UInt32..."
                      />
                      <Input
                        label="Кодеки сжатия"
                        value={allowedCodecs}
                        onChange={(e) => setAllowedCodecs(e.target.value)}
                        placeholder="ZSTD, LZ4HC, DoubleDelta..."
                      />
                      <Input
                        label="Кандидаты для ключа сортировки (ORDER BY)"
                        value={allowedOrderBy}
                        onChange={(e) => setAllowedOrderBy(e.target.value)}
                        placeholder="created_at, user_id..."
                      />
                    </div>

                    {/* Block: Нагрузка и оценка */}
                    <div className="space-y-2.5">
                      <div className="text-xs font-bold text-slate-800 dark:text-slate-200">
                        Блок «Нагрузка и оценка»
                      </div>
                      <Input
                        label="Бюджет времени эксперимента (мин)"
                        type="number"
                        value={timeBudget}
                        onChange={(e) => setTimeBudget(e.target.value)}
                      />
                      <Input
                        label="Максимальное количество кандидатов"
                        type="number"
                        value={maxCandidates}
                        onChange={(e) => setMaxCandidates(e.target.value)}
                      />
                      <Select label="Цель оптимизации" defaultValue="balanced">
                        <option value="query_speed">Максимальное ускорение запросов</option>
                        <option value="disk_size">Минимальный объём на диске</option>
                        <option value="balanced">Сбалансированный профиль (скорость + сжатие)</option>
                      </Select>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Wizard Controls Footer */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-[#242C38]">
          <Button
            variant="ghost"
            onClick={() => {
              if (currentStep === 1) setCurrentTab('benchmarks');
              else setCurrentStep((s) => (s - 1) as 1 | 2 | 3);
            }}
          >
            {currentStep === 1 ? 'Отмена' : 'Назад'}
          </Button>

          <div className="flex items-center gap-2">
            {currentStep < 3 ? (
              <Button
                variant="primary"
                onClick={() => setCurrentStep((s) => (s + 1) as 1 | 2 | 3)}
                disabled={
                  (currentStep === 1 && !isStep1Valid) ||
                  (currentStep === 2 && !isStep2Valid)
                }
              >
                <span>Далее</span>
                <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={handleFinish}
                disabled={!isStep1Valid || !isStep2Valid || !isStep3Valid}
              >
                Сохранить бенчмарк
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
