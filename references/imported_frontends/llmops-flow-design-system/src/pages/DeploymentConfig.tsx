import React, { useState } from 'react';
import {
  Settings,
  Cpu,
  Zap,
  Check,
  RotateCcw,
  ShieldAlert,
  Save,
  Sparkles,
  Info,
  Layers,
  Search,
  CheckSquare,
  Square
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useLanguage } from '../context/LanguageContext';

interface ModelProfile {
  name: string;
  type: 'text' | 'vision';
  cpuRam: string;
  gpuRam: string;
}

const INITIAL_MODELS: ModelProfile[] = [
  { name: 'deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'tiiuae/Falcon3-1B-Base (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'tiiuae/Falcon3-1B-Instruct (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'tiiuae/Falcon3-3B-Base (только текст)', type: 'text', cpuRam: '7Gi', gpuRam: '7Gi' },
  { name: 'tiiuae/Falcon3-3B-Instruct (только текст)', type: 'text', cpuRam: '7Gi', gpuRam: '7Gi' },
  { name: 'HuggingFaceTB/SmolLM-135M (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'HuggingFaceTB/SmolLM-360M (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'HuggingFaceTB/SmolLM2-135M-Instruct (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'HuggingFaceTB/SmolLM2-360M-Instruct (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'google/gemma-3-1b-it (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'google/gemma-2-2b-it (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'google/gemma-3-4b-it (только текст)', type: 'text', cpuRam: '7Gi', gpuRam: '7Gi' },
  { name: 'Qwen/QwQ-0.5B (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'Qwen/Qwen2-0.5B (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'Qwen/Qwen2-0.5B-Instruct (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'Qwen/Qwen2.5-0.5B (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'Qwen/Qwen2.5-0.5B-Instruct (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'Qwen/Qwen2.5-Coder-0.5B-Instruct (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'Qwen/Qwen3-0.6B (только текст)', type: 'text', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'Qwen/Qwen2.5-1.5B-Instruct (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'Qwen/Qwen3-1.7B (только текст)', type: 'text', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'Qwen/Qwen2.5-3B-Instruct (только текст)', type: 'text', cpuRam: '7Gi', gpuRam: '7Gi' },
  { name: 'HuggingFaceTB/SmolVLM-256M-Instruct (текст + картинки)', type: 'vision', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'HuggingFaceTB/SmolVLM-500M-Instruct (текст + картинки)', type: 'vision', cpuRam: '5Gi', gpuRam: '5Gi' },
  { name: 'HuggingFaceTB/SmolVLM2-2.2B-Instruct (текст + картинки)', type: 'vision', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'vikhyatk/moondream2 (текст + картинки)', type: 'vision', cpuRam: '4Gi', gpuRam: '4Gi' },
  { name: 'OpenGVLab/InternVL2-1B (текст + картинки)', type: 'vision', cpuRam: '5Gi', gpuRam: '5Gi' },
  { name: 'OpenGVLab/InternVL2-2B (текст + картинки)', type: 'vision', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'Qwen/Qwen2.5-VL-3B-Instruct (текст + картинки)', type: 'vision', cpuRam: '6Gi', gpuRam: '6Gi' },
  { name: 'microsoft/Phi-3.5-vision-instruct (текст + картинки)', type: 'vision', cpuRam: '6Gi', gpuRam: '6Gi' }
];

const CPU_TYPES = [
  { id: 'intel(r) core(tm) i3-2120 cpu @ 3.30ghz', shortName: 'Intel Core i3', fullName: 'intel(r) core(tm) i3-2120 cpu @ 3.30ghz' },
  { id: 'amd-epyc-7002-32-core', shortName: 'AMD EPYC 7002', fullName: 'AMD EPYC 7002 Server Processor' },
  { id: 'intel-xeon-gold-6248r', shortName: 'Intel Xeon Gold', fullName: 'Intel Xeon Gold 6248R @ 3.00GHz' }
];

const GPU_TYPES = [
  { id: 'Tesla V100-SXM2-16GB', shortName: 'Tesla V100', fullName: 'Tesla V100-SXM2-16GB' },
  { id: 'NVIDIA-A100-SXM4-80GB', shortName: 'NVIDIA A100', fullName: 'NVIDIA A100 SXM4 80GB' },
  { id: 'NVIDIA-A10G-24GB', shortName: 'NVIDIA A10G', fullName: 'NVIDIA A10G 24GB' }
];

export function DeploymentConfig() {
  const { t, language } = useLanguage();
  const [defaultCpuRam, setDefaultCpuRam] = useState('6Gi');
  const [defaultGpuRam, setDefaultGpuRam] = useState('6Gi');

  const [models, setModels] = useState<ModelProfile[]>(INITIAL_MODELS);

  // Selection arrays for limits
  const [allCpuChecked, setAllCpuChecked] = useState<string[]>(
    INITIAL_MODELS.filter(m => !m.name.includes('Falcon') && !m.name.includes('DeepSeek') && !m.name.includes('gemma') && !m.name.includes('1.5B') && !m.name.includes('3B')).map(m => m.name)
  );
  const [allGpuChecked, setAllGpuChecked] = useState<string[]>(
    INITIAL_MODELS.map(m => m.name)
  );

  const [selectedCpuType, setSelectedCpuType] = useState('intel(r) core(tm) i3-2120 cpu @ 3.30ghz');
  const [cpuTypeMap, setCpuTypeMap] = useState<Record<string, string[]>>({
    'intel(r) core(tm) i3-2120 cpu @ 3.30ghz': INITIAL_MODELS.filter(m => !m.name.includes('Falcon') && !m.name.includes('DeepSeek') && !m.name.includes('gemma') && !m.name.includes('1.5B') && !m.name.includes('3B')).map(m => m.name),
    'amd-epyc-7002-32-core': INITIAL_MODELS.filter(m => !m.name.includes('Falcon3-3B')).map(m => m.name),
    'intel-xeon-gold-6248r': INITIAL_MODELS.map(m => m.name)
  });

  const [selectedGpuType, setSelectedGpuType] = useState('Tesla V100-SXM2-16GB');
  const [gpuTypeMap, setGpuTypeMap] = useState<Record<string, string[]>>({
    'Tesla V100-SXM2-16GB': INITIAL_MODELS.map(m => m.name),
    'NVIDIA-A100-SXM4-80GB': INITIAL_MODELS.map(m => m.name),
    'NVIDIA-A10G-24GB': INITIAL_MODELS.filter(m => !m.name.includes('Falcon3')).map(m => m.name)
  });

  const [success, setSuccess] = useState<string | null>(null);

  const handleCpuModelToggle = (modelName: string) => {
    if (allCpuChecked.includes(modelName)) {
      setAllCpuChecked(allCpuChecked.filter(m => m !== modelName));
    } else {
      setAllCpuChecked([...allCpuChecked, modelName]);
    }
  };

  const handleGpuModelToggle = (modelName: string) => {
    if (allGpuChecked.includes(modelName)) {
      setAllGpuChecked(allGpuChecked.filter(m => m !== modelName));
    } else {
      setAllGpuChecked([...allGpuChecked, modelName]);
    }
  };

  const handleCpuTypeModelToggle = (type: string, modelName: string) => {
    const current = cpuTypeMap[type] || [];
    let updated: string[];
    if (current.includes(modelName)) {
      updated = current.filter(m => m !== modelName);
    } else {
      updated = [...current, modelName];
    }
    setCpuTypeMap({
      ...cpuTypeMap,
      [type]: updated
    });
  };

  const handleGpuTypeModelToggle = (type: string, modelName: string) => {
    const current = gpuTypeMap[type] || [];
    let updated: string[];
    if (current.includes(modelName)) {
      updated = current.filter(m => m !== modelName);
    } else {
      updated = [...current, modelName];
    }
    setGpuTypeMap({
      ...gpuTypeMap,
      [type]: updated
    });
  };

  const handleClearCpuType = (type: string) => {
    setCpuTypeMap({
      ...cpuTypeMap,
      [type]: []
    });
  };

  const handleClearGpuType = (type: string) => {
    setGpuTypeMap({
      ...gpuTypeMap,
      [type]: []
    });
  };

  const handleSave = () => {
    setSuccess(
      language === 'ru'
        ? 'Конфигурация ограничений успешно сохранена и синхронизирована с API кластеров Kubernetes!'
        : 'Limit configuration successfully saved and synchronized with Kubernetes cluster API!'
    );
    setTimeout(() => setSuccess(null), 5000);
  };

  const filteredModels = models;

  return (
    <div className="space-y-8 max-w-7xl mx-auto pb-20">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2.5">
            <Settings className="w-7 h-7 text-indigo-500" />
            {language === 'ru' ? 'Конфиг деплойментов' : 'Deployment Config'}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {language === 'ru'
              ? 'Ограничения LLM по CPU/GPU и системные профили моделей'
              : 'LLM CPU/GPU restrictions and system model profiles'}
          </p>
        </div>
      </div>

      {success && (
        <div className="bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-550/25 text-emerald-800 dark:text-emerald-400 p-4 rounded-xl flex items-center gap-3 text-sm font-medium animate-fade-in shadow-sm">
          <Check className="w-5 h-5 text-emerald-600" />
          {success}
        </div>
      )}

      {/* Info Notice block */}
      <div className="bg-indigo-50/20 dark:bg-indigo-550/5 border border-indigo-100 dark:border-indigo-500/10 p-4 rounded-xl flex items-start gap-3.5 text-xs text-indigo-950 dark:text-indigo-200 leading-relaxed font-medium">
        <Info className="w-5 h-5 text-indigo-500 shrink-0 mt-0.5" />
        <div>
          {language === 'ru'
            ? 'Выберите из общего списка моделей, что разрешено запускать: на всех CPU, на всех GPU, а также на конкретных типах CPU/GPU. Данные ограничения жестко валидируются на уровне веб-клиента и REST API при вызове процедуры создания нового деплоймента.'
            : 'Select from the general list of models which are allowed to run: on all CPUs, on all GPUs, as well as on specific CPU/GPU types. These limits are strictly validated at the web-client and REST API levels when creating a new model deployment.'}
        </div>
      </div>

      {/* Grid: Profiles */}
      <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm space-y-6">
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-900 pb-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500 dark:text-slate-400">
            {language === 'ru' ? 'Профили моделей' : 'Model Profiles'}
          </h3>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-gray-400 dark:text-gray-500">Default CPU RAM:</span>
              <input
                type="text"
                value={defaultCpuRam}
                onChange={(e) => setDefaultCpuRam(e.target.value)}
                className="w-16 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded px-2 py-0.5 text-xs font-bold text-center outline-none focus:ring-1 focus:ring-indigo-500 text-gray-900 dark:text-white"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-gray-400 dark:text-gray-500">Default GPU RAM:</span>
              <input
                type="text"
                value={defaultGpuRam}
                onChange={(e) => setDefaultGpuRam(e.target.value)}
                className="w-16 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded px-2 py-0.5 text-xs font-bold text-center outline-none focus:ring-1 focus:ring-indigo-500 text-gray-900 dark:text-white"
              />
            </div>
          </div>
        </div>

        <div className="overflow-x-auto border border-gray-100 dark:border-slate-900 rounded-xl">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="bg-gray-50 dark:bg-slate-900/60 text-gray-500 font-bold uppercase tracking-wider border-b border-gray-100 dark:border-slate-900">
                <th className="px-6 py-3.5">{language === 'ru' ? 'Модель' : 'Model'}</th>
                <th className="px-6 py-3.5">CPU RAM</th>
                <th className="px-6 py-3.5">GPU RAM</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-900">
              {filteredModels.map((m, index) => (
                <tr key={index} className="hover:bg-gray-50/50 dark:hover:bg-slate-900/20 transition-colors">
                  <td className="px-6 py-3 font-medium text-gray-800 dark:text-slate-200">{m.name}</td>
                  <td className="px-6 py-3">
                    <input
                      type="text"
                      placeholder={defaultCpuRam}
                      value={m.cpuRam}
                      onChange={(e) => {
                        const next = [...models];
                        next[index].cpuRam = e.target.value;
                        setModels(next);
                      }}
                      className="w-20 bg-white dark:bg-slate-900 border border-gray-250 dark:border-slate-800 rounded-md px-2.5 py-1 text-xs font-semibold text-gray-900 dark:text-white outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </td>
                  <td className="px-6 py-3">
                    <input
                      type="text"
                      placeholder={defaultGpuRam}
                      value={m.gpuRam}
                      onChange={(e) => {
                        const next = [...models];
                        next[index].gpuRam = e.target.value;
                        setModels(next);
                      }}
                      className="w-20 bg-white dark:bg-slate-900 border border-gray-250 dark:border-slate-800 rounded-md px-2.5 py-1 text-xs font-semibold text-gray-900 dark:text-white outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-gray-400 dark:text-slate-400 italic mt-2">
          {language === 'ru'
            ? 'Формат значений: например 4Gi, 6144Mi. Пустое значение в строке модели означает использование по умолчанию.'
            : 'Value format: e.g. 4Gi, 6144Mi. Empty configuration field defaults to predefined cluster profiles.'}
        </p>
      </div>

      {/* Allowed hardware checklists */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* All CPU Section */}
        <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm flex flex-col h-[480px]">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-900 pb-3 mb-4 shrink-0">
            <div className="flex items-center gap-2">
              <Cpu className="w-5 h-5 text-amber-500" />
              <h3 className="font-bold text-gray-900 dark:text-white">{language === 'ru' ? 'Все CPU' : 'All CPUs'}</h3>
            </div>
            <span className="text-xs bg-amber-50 dark:bg-amber-500/10 text-amber-600 px-2 py-0.5 rounded-full font-bold">
              {allCpuChecked.length} {language === 'ru' ? 'разрешено' : 'allowed'}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 pr-1 custom-scrollbar">
            {models.map(m => {
              const checked = allCpuChecked.includes(m.name);
              return (
                <label
                  key={m.name}
                  className={`flex items-start gap-2.5 p-2 rounded-lg cursor-pointer transition-colors ${
                    checked
                      ? 'bg-indigo-50/20 dark:bg-indigo-500/5 text-gray-900 dark:text-white font-medium'
                      : 'hover:bg-gray-50 dark:hover:bg-slate-900/40 text-gray-500 dark:text-slate-300'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => handleCpuModelToggle(m.name)}
                    className="mt-0.5 rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900"
                  />
                  <span className="text-xs font-semibold leading-normal">{m.name}</span>
                </label>
              );
            })}
          </div>
        </div>

        {/* All GPU Section */}
        <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm flex flex-col h-[480px]">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-900 pb-3 mb-4 shrink-0">
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-purple-500" />
              <h3 className="font-bold text-gray-900 dark:text-white">{language === 'ru' ? 'Все GPU' : 'All GPUs'}</h3>
            </div>
            <span className="text-xs bg-purple-50 dark:bg-purple-500/10 text-purple-600 px-2 py-0.5 rounded-full font-bold">
              {allGpuChecked.length} {language === 'ru' ? 'разрешено' : 'allowed'}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 pr-1 custom-scrollbar">
            {models.map(m => {
              const checked = allGpuChecked.includes(m.name);
              return (
                <label
                  key={m.name}
                  className={`flex items-start gap-2.5 p-2 rounded-lg cursor-pointer transition-colors ${
                    checked
                      ? 'bg-indigo-50/20 dark:bg-indigo-500/5 text-gray-900 dark:text-white font-medium'
                      : 'hover:bg-gray-50 dark:hover:bg-slate-900/40 text-gray-500 dark:text-slate-300'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => handleGpuModelToggle(m.name)}
                    className="mt-0.5 rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 border-gray-300 dark:border-slate-750 bg-white dark:bg-slate-900"
                  />
                  <span className="text-xs font-semibold leading-normal">{m.name}</span>
                </label>
              );
            })}
          </div>
        </div>
      </div>

      {/* Selected hardware types restrictions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Selected CPU Specific Type */}
        <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm flex flex-col h-[520px]">
          <div className="border-b border-gray-100 dark:border-slate-900 pb-3 mb-4 shrink-0 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              <h3 className="font-bold text-gray-900 dark:text-white text-sm">
                {language === 'ru' ? 'Специфичные настройки CPU' : 'Specific CPU Configuration'}
              </h3>
            </div>
            <button
              onClick={() => handleClearCpuType(selectedCpuType)}
              className="text-[10px] uppercase font-bold text-red-500 hover:text-red-700 transition-colors flex items-center gap-1.5 bg-red-50 dark:bg-red-500/5 px-2.5 py-1 rounded"
            >
              {language === 'ru' ? 'Очистить модели' : 'Clear Models'}
            </button>
          </div>

          <div className="flex-1 flex gap-4 min-h-0">
            {/* Left menu: CPU types */}
            <div className="w-1/3 flex flex-col gap-1.5 border-r border-gray-150 dark:border-slate-900 pr-3 overflow-y-auto w-[120px] shrink-0">
              {CPU_TYPES.map(cpu => {
                const isSelected = selectedCpuType === cpu.id;
                const allowedCount = (cpuTypeMap[cpu.id] || []).length;
                return (
                  <button
                    key={cpu.id}
                    type="button"
                    onClick={() => setSelectedCpuType(cpu.id)}
                    className={cn(
                      "p-3 rounded-lg text-left transition-all space-y-1 bg-transparent border text-xs block w-full",
                      isSelected
                        ? "bg-indigo-50/50 dark:bg-indigo-500/10 border-indigo-200 dark:border-indigo-500/20 text-indigo-650 dark:text-indigo-400 font-semibold"
                        : "hover:bg-gray-50 dark:hover:bg-slate-900 border-transparent text-gray-500 dark:text-slate-300"
                    )}
                  >
                    <div className="font-bold uppercase tracking-wider block truncate">{cpu.shortName}</div>
                    <div className="text-[10px] opacity-75 block truncate">{cpu.fullName}</div>
                    <div className="text-[10px] text-indigo-500 font-bold block mt-1">
                      {allowedCount} {language === 'ru'
                        ? (allowedCount === 1 ? 'модель' : allowedCount > 1 && allowedCount < 5 ? 'модели' : 'моделей')
                        : (allowedCount === 1 ? 'model' : 'models')}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Right checklist: Models allowed for this CPU */}
            <div className="flex-1 overflow-y-auto space-y-1 pr-1 custom-scrollbar">
              {models.map(m => {
                const checked = (cpuTypeMap[selectedCpuType] || []).includes(m.name);
                return (
                  <label
                    key={m.name}
                    className={`flex items-start gap-2.5 p-2 rounded-lg cursor-pointer transition-colors ${
                      checked
                        ? 'bg-indigo-50/20 dark:bg-indigo-500/5 text-gray-900 dark:text-white font-medium'
                        : 'hover:bg-gray-50 dark:hover:bg-slate-900/40 text-gray-500 dark:text-slate-300'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => handleCpuTypeModelToggle(selectedCpuType, m.name)}
                      className="mt-0.5 rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900"
                    />
                    <span className="text-xs font-semibold leading-normal">{m.name}</span>
                  </label>
                );
              })}
            </div>
          </div>
        </div>

        {/* Selected GPU Specific Type */}
        <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm flex flex-col h-[520px]">
          <div className="border-b border-gray-100 dark:border-slate-900 pb-3 mb-4 shrink-0 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-purple-650 dark:text-purple-450" />
              <h3 className="font-bold text-gray-900 dark:text-white text-sm">
                {language === 'ru' ? 'Специфичные настройки GPU' : 'Specific GPU Configuration'}
              </h3>
            </div>
            <button
              onClick={() => handleClearGpuType(selectedGpuType)}
              className="text-[10px] uppercase font-bold text-red-5  00 hover:text-red-700 transition-colors flex items-center gap-1.5 bg-red-50 dark:bg-red-500/5 px-2.5 py-1 rounded"
            >
              {language === 'ru' ? 'Очистить модели' : 'Clear Models'}
            </button>
          </div>

          <div className="flex-1 flex gap-4 min-h-0">
            {/* Left menu: GPU types */}
            <div className="w-1/3 flex flex-col gap-1.5 border-r border-gray-150 dark:border-slate-900 pr-3 overflow-y-auto w-[120px] shrink-0">
              {GPU_TYPES.map(gpu => {
                const isSelected = selectedGpuType === gpu.id;
                const allowedCount = (gpuTypeMap[gpu.id] || []).length;
                return (
                  <button
                    key={gpu.id}
                    type="button"
                    onClick={() => setSelectedGpuType(gpu.id)}
                    className={cn(
                      "p-3 rounded-lg text-left transition-all space-y-1 bg-transparent border text-xs block w-full",
                      isSelected
                        ? "bg-purple-50/50 dark:bg-purple-500/10 border-purple-200 dark:border-purple-500/20 text-purple-650 dark:text-purple-400 font-semibold"
                        : "hover:bg-gray-50 dark:hover:bg-slate-900 border-transparent text-gray-500 dark:text-slate-300"
                    )}
                  >
                    <div className="font-bold uppercase tracking-wider block truncate">{gpu.shortName}</div>
                    <div className="text-[10px] opacity-75 block truncate">{gpu.fullName}</div>
                    <div className="text-[10px] text-purple-500 font-bold block mt-1">
                      {allowedCount} {language === 'ru'
                        ? (allowedCount === 1 ? 'модель' : allowedCount > 1 && allowedCount < 5 ? 'модели' : 'моделей')
                        : (allowedCount === 1 ? 'model' : 'models')}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Right checklist: Models allowed for this GPU */}
            <div className="flex-1 overflow-y-auto space-y-1 pr-1 custom-scrollbar">
              {models.map(m => {
                const checked = (gpuTypeMap[selectedGpuType] || []).includes(m.name);
                return (
                  <label
                    key={m.name}
                    className={`flex items-start gap-2.5 p-2 rounded-lg cursor-pointer transition-colors ${
                      checked
                        ? 'bg-purple-50/10 dark:bg-purple-500/5 text-gray-900 dark:text-white font-medium'
                        : 'hover:bg-gray-50 dark:hover:bg-slate-900/40 text-gray-500 dark:text-slate-300'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => handleGpuTypeModelToggle(selectedGpuType, m.name)}
                      className="mt-0.5 rounded text-purple-600 focus:ring-purple-500 h-4 w-4 border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900"
                    />
                    <span className="text-xs font-semibold leading-normal">{m.name}</span>
                  </label>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Action button bar */}
      <div className="flex justify-end p-6 bg-slate-50 dark:bg-slate-900/30 rounded-2xl border border-gray-200 dark:border-slate-800/80">
        <button
          onClick={handleSave}
          className="px-6 py-3.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold uppercase tracking-wider shadow-md transition-all flex items-center gap-2.5"
        >
          <Save className="w-4 h-4" />
          {language === 'ru' ? 'Сохранить ограничения' : 'Save Restrictions'}
        </button>
      </div>
    </div>
  );
}
