import React, { useState } from 'react';
import {
  Layers,
  Plus,
  ArrowRight,
  Sparkles,
  CheckCircle2,
  FileCode,
  Info,
} from 'lucide-react';
import { useBenchmark } from '../context/BenchmarkContext';
import { StrategyTemplate, StrategyTechnicalType } from '../types';
import { Button, Modal, Input, Select, NoticeBanner } from '../components/ui/GpbComponents';

export const StrategiesView: React.FC = () => {
  const { strategies, createStrategy, setPreselectedStrategyId, setCurrentTab } =
    useBenchmark();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [name, setName] = useState('');
  const [techType, setTechType] = useState<StrategyTechnicalType>(
    'sequential_phased_topn_strategy'
  );
  const [phasesInput, setPhasesInput] = useState('Анализ предикатов, Подбор индексов, Верификация');
  const [description, setDescription] = useState('');

  const technicalMapping: Record<StrategyTechnicalType, string> = {
    sequential_phased_topn_strategy: 'Поэтапный подбор структуры',
    types_strategy: 'Подбор типов колонок',
    indexes_strategy: 'Подбор skip-индексов',
    sequential_topn_strategy: 'Подбор порядка сортировки',
  };

  const handleCreateBenchmarkBasedOn = (stratId: string) => {
    setPreselectedStrategyId(stratId);
    setCurrentTab('benchmark-create');
  };

  const handleCreateStrategySubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    const phases = phasesInput
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean);

    createStrategy({
      name: name.trim(),
      technicalType: techType,
      phases: phases.length > 0 ? phases : ['Фаза 1: Оценка'],
      description: description.trim() || 'Пользовательский шаблон стратегии оптимизации',
    });

    setName('');
    setDescription('');
    setPhasesInput('Анализ предикатов, Подбор индексов, Верификация');
    setIsModalOpen(false);
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Стратегии поиска
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Служебный каталог переиспользуемых базовых шаблонов для перебора вариантов структуры
            таблиц
          </p>
        </div>

        <Button
          id="create-strategy-btn"
          variant="primary"
          icon={Plus}
          onClick={() => setIsModalOpen(true)}
        >
          Создать шаблон стратегии
        </Button>
      </div>

      {/* Info notice per Section 9 */}
      <NoticeBanner type="info" title="Понятные названия и архитектурное версионирование">
        В интерфейсе отображаются понятные имена стратегий вместо сырых системных ключей. Изменение
        общего шаблона не изменяет ранее настроенные бенчмарки и историю запусков: конфигурация
        копируется при создании бенчмарка.
      </NoticeBanner>

      {/* Strategy Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {strategies.map((strat) => {
          return (
            <div
              key={strat.id}
              className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-5 flex flex-col justify-between shadow-2xs hover:border-slate-300 dark:hover:border-[#384353] transition-all"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                      {strat.name}
                    </h3>
                    <div className="flex items-center gap-1.5 mt-1">
                      <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-[#202734] px-1.5 py-0.5 rounded border border-slate-200 dark:border-[#303B4A]">
                        {strat.technicalType}
                      </span>
                      {strat.isBuiltin && (
                        <span className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">
                          Базовый шаблон
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="w-8 h-8 rounded bg-blue-50 dark:bg-blue-950/40 text-[#0033A0] dark:text-blue-400 flex items-center justify-center shrink-0">
                    <Layers className="w-4 h-4" />
                  </div>
                </div>

                <p className="mt-3 text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                  {strat.description}
                </p>

                {/* Phases list */}
                <div className="mt-4 pt-3 border-t border-slate-100 dark:border-[#242C38]">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-2">
                    Этапы поиска ({strat.phases.length}):
                  </div>
                  <ol className="space-y-1.5">
                    {strat.phases.map((phase, index) => (
                      <li
                        key={index}
                        className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300"
                      >
                        <span className="w-4 h-4 rounded-full bg-slate-100 dark:bg-[#202734] text-[10px] font-mono font-medium flex items-center justify-center text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-[#2E3846] shrink-0">
                          {index + 1}
                        </span>
                        <span>{phase}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>

              {/* Action Button: Create Benchmark based on this strategy */}
              <div className="mt-5 pt-3 border-t border-slate-100 dark:border-[#242C38] flex items-center justify-end">
                <Button
                  size="sm"
                  variant="secondary"
                  icon={ArrowRight}
                  onClick={() => handleCreateBenchmarkBasedOn(strat.id)}
                >
                  Создать бенчмарк на основе
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Modal: Create Strategy Template */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Создать шаблон стратегии"
        subtitle="Новый переиспользуемый шаблон перебора физической структуры"
        footer={
          <>
            <Button variant="ghost" onClick={() => setIsModalOpen(false)}>
              Отмена
            </Button>
            <Button
              variant="primary"
              onClick={handleCreateStrategySubmit}
              disabled={!name.trim()}
            >
              Сохранить шаблон
            </Button>
          </>
        }
      >
        <form onSubmit={handleCreateStrategySubmit} className="space-y-4">
          <Input
            label="Понятное название шаблона"
            required
            placeholder="Например: Оптимизация skip-индексов для телеметрии"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />

          <Select
            label="Технический тип стратегии"
            value={techType}
            onChange={(e) => setTechType(e.target.value as StrategyTechnicalType)}
          >
            <option value="sequential_phased_topn_strategy">
              sequential_phased_topn_strategy (Поэтапный подбор структуры)
            </option>
            <option value="types_strategy">types_strategy (Подбор типов колонок)</option>
            <option value="indexes_strategy">indexes_strategy (Подбор skip-индексов)</option>
            <option value="sequential_topn_strategy">
              sequential_topn_strategy (Подбор порядка сортировки)
            </option>
          </Select>

          <Input
            label="Этапы поиска (через запятую)"
            required
            value={phasesInput}
            onChange={(e) => setPhasesInput(e.target.value)}
            helperText="Список последовательных шагов формирования вариантов."
          />

          <Input
            label="Краткое описание"
            placeholder="Назначение и особенности данной стратегии"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </form>
      </Modal>
    </div>
  );
};
