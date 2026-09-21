import { useState } from 'react';
import {
  Palette,
  Type,
  CornerDownRight,
  HelpCircle,
  Play,
  Plus,
  Check,
  Sparkles,
  Terminal,
  Moon,
  Sun,
  Badge,
  Sliders,
  Smartphone,
  Monitor,
  Cpu,
  Zap,
  AlertTriangle,
  X,
  RefreshCw,
  GitCommit,
  Eye,
  EyeOff,
  Copy,
  ChevronDown,
  Info,
  CheckCircle2,
  Trash2,
  ExternalLink,
  Lock,
  Search,
  MoreVertical,
  SlidersHorizontal,
  FolderOpen
} from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import { motion, AnimatePresence } from 'motion/react';

interface DesignSystemProps {
  activeSection: 'all' | 'colors' | 'typography' | 'components' | 'sandbox';
  onSectionChange: (sec: 'all' | 'colors' | 'typography' | 'components' | 'sandbox') => void;
}

export function DesignSystem({ activeSection, onSectionChange }: DesignSystemProps) {
  const { language } = useLanguage();
  const isRu = language === 'ru';

  // State managers
  const [toggleVal, setToggleVal] = useState<boolean>(true);
  const [checkboxVal, setCheckboxVal] = useState<boolean>(true);
  const [radioVal, setRadioVal] = useState<'h100' | 'a100' | 't4'>('h100');
  const [apiKeyVisible, setApiKeyVisible] = useState<boolean>(false);
  const [copiedText, setCopiedText] = useState<boolean>(false);
  const [selectedDropdownOption, setSelectedDropdownOption] = useState<string>('eu-west-1');
  const [showDropdownMock, setShowDropdownMock] = useState<boolean>(false);
  const [showModalMock, setShowModalMock] = useState<boolean>(false);

  // Toast notifications mock
  const [toasts, setToasts] = useState<{ id: number; type: 'success' | 'info' | 'error'; text: string }[]>([]);

  // Interactive sandbox state
  const [sandboxTheme, setSandboxTheme] = useState<'indigo' | 'emerald' | 'amber' | 'rose'>('indigo');
  const [sandboxReplicas, setSandboxReplicas] = useState<number>(4);
  const [sandboxStatus, setSandboxStatus] = useState<'ready' | 'pending' | 'failed'>('ready');
  const [isSandboxPulsing, setIsSandboxPulsing] = useState<boolean>(true);
  const [mockLoadingState, setMockLoadingState] = useState<boolean>(false);

  // Trigger copy preview mock
  const triggerCopy = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedText(true);
    setTimeout(() => setCopiedText(false), 2000);
  };

  const addMockToast = (type: 'success' | 'info' | 'error', text: string) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, type, text }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  const themeColors = {
    indigo: {
      bg: 'bg-indigo-50 dark:bg-indigo-950/20',
      border: 'border-indigo-200 dark:border-indigo-800/40',
      text: 'text-indigo-700 dark:text-indigo-400',
      badge: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300',
      fill: 'bg-indigo-600 hover:bg-indigo-700 text-white focus:ring-indigo-500/30',
    },
    emerald: {
      bg: 'bg-emerald-50 dark:bg-emerald-950/20',
      border: 'border-emerald-200 dark:border-emerald-800/40',
      text: 'text-emerald-700 dark:text-emerald-400',
      badge: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
      fill: 'bg-emerald-600 hover:bg-emerald-700 text-white focus:ring-emerald-500/30',
    },
    amber: {
      bg: 'bg-amber-50 dark:bg-amber-950/20',
      border: 'border-amber-200 dark:border-amber-800/40',
      text: 'text-amber-700 dark:text-amber-400',
      badge: 'bg-amber-100 text-amber-850 dark:bg-amber-900/30 dark:text-amber-305',
      fill: 'bg-amber-500 hover:bg-amber-600 text-white focus:ring-amber-500/30',
    },
    rose: {
      bg: 'bg-rose-50 dark:bg-rose-950/20',
      border: 'border-rose-200 dark:border-rose-800/40',
      text: 'text-rose-700 dark:text-rose-400',
      badge: 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300',
      fill: 'bg-rose-600 hover:bg-rose-700 text-white focus:ring-rose-500/30',
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-12 pb-24 relative">

      {/* Toast Alert Canvas Overlays */}
      <div className="fixed bottom-6 right-6 z-50 space-y-2 pointer-events-none max-w-sm w-full">
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.9 }}
              className="pointer-events-auto w-full p-4 rounded-xl border bg-white dark:bg-slate-950 shadow-lg border-gray-200 dark:border-slate-800 flex items-start gap-3"
            >
              {toast.type === 'success' && <CheckCircle2 className="w-5 h-5 text-emerald-500 flex-shrink-0 mt-0.5" />}
              {toast.type === 'info' && <Info className="w-5 h-5 text-indigo-500 flex-shrink-0 mt-0.5" />}
              {toast.type === 'error' && <AlertTriangle className="w-5 h-5 text-rose-500 flex-shrink-0 mt-0.5" />}
              <div className="flex-1 text-left">
                <span className="text-xs font-semibold text-gray-900 dark:text-white capitalize block">
                  {toast.type === 'success' ? (isRu ? 'Выполнено' : 'Success') : toast.type === 'info' ? (isRu ? 'Инфо' : 'Information') : (isRu ? 'Системный сбой' : 'Alert Triggered')}
                </span>
                <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-0.5 leading-relaxed">{toast.text}</p>
              </div>
              <button onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))} className="text-gray-400 hover:text-gray-900 dark:hover:text-white">
                <X className="w-3.5 h-3.5" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Hero Header Spec */}
      <div className="relative overflow-hidden rounded-2xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-8 shadow-sm transition-colors duration-200">
        <div className="absolute right-0 top-0 -mr-16 -mt-16 w-56 h-56 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute left-1/3 bottom-0 w-80 h-32 bg-emerald-500/5 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-bold bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-400 border border-indigo-200/30">
              <Sparkles className="w-3.5 h-3.5" />
              <span>{isRu ? 'Реальные элементы интерфейса без исключений' : 'The Absolute Full Interface Spec'}</span>
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-gray-950 dark:text-white font-sans">
              {isRu ? 'Интерактивная Панель Компонентов' : 'Master Components Palette'}
            </h1>
            <p className="text-sm text-gray-500 dark:text-slate-400 max-w-2xl leading-relaxed">
              {isRu
                ? 'Полный разбор всех визуальных сущностей нашей дизайн-системы. Здесь представлены абсолютно все элементы без исключений: кнопки во всех состояниях, поля ввода, комплексные интерактивные таблицы, всплывающие уведомления, слайдеры, радио-кнопки, а также модульные модальные окна.'
                : 'Interactive display of all real UI primitives. Includes buttons with loaded states, complex tabular matrices, standard forms, modal templates, alerts, range pickers, key visualizers, and state modifiers.'
              }
            </p>
          </div>

          {/* Quick tab helpers */}
          <div className="flex items-center gap-2 self-start md:self-center bg-gray-100 dark:bg-slate-900 p-1 rounded-lg border border-gray-250 dark:border-slate-800/80">
            <button
              onClick={() => onSectionChange('all')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${activeSection === 'all' ? 'bg-white dark:bg-slate-800 text-gray-900 dark:text-white shadow-sm font-bold' : 'text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white'}`}
            >
              {isRu ? 'Всё сразу' : 'All Components'}
            </button>
            <button
              onClick={() => onSectionChange('components')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${activeSection === 'components' ? 'bg-white dark:bg-slate-800 text-gray-900 dark:text-white shadow-sm font-bold' : 'text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white'}`}
            >
              {isRu ? 'Элементы' : 'Primitives'}
            </button>
            <button
              onClick={() => onSectionChange('colors')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${activeSection === 'colors' ? 'bg-white dark:bg-slate-800 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white'}`}
            >
              {isRu ? 'Цвета и Стили' : 'Visual Styles'}
            </button>
            <button
              onClick={() => onSectionChange('sandbox')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${activeSection === 'sandbox' ? 'bg-white dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 shadow-sm font-bold' : 'text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white'}`}
            >
              🛠️ {isRu ? 'Песочница' : 'Sandbox'}
            </button>
          </div>
        </div>
      </div>

      {/* RENDER BODY SECTIONS */}
      <div className="space-y-16">

        {/* SECTION A: BUTTONS AND SMALL ACTION PRIMITIVES */}
        {(activeSection === 'all' || activeSection === 'components') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-indigo-500/10 rounded-lg text-indigo-500">
                <Sliders className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '1. Кнопки и Нажимаемые Элементы' : '1. Buttons & Touch Action Primitives'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Все комбинации стилей кнопок с поддержкой интерактивных микро-стейтов.' : 'A precise compilation of button surfaces, icons, loadings, and toggle components.'}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

              {/* BUTTON SPEC CARD */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-6 rounded-2xl shadow-xs space-y-6 text-left">
                <div>
                  <h3 className="text-xs font-bold text-gray-400 dark:text-slate-500 uppercase tracking-widest font-mono">Variants & Colors</h3>
                  <p className="text-xs text-gray-500 mt-1">{isRu ? 'Основные цветовые роли интерфейса' : 'Interface visual roles'}</p>
                </div>

                <div className="flex flex-wrap gap-3">
                  <button onClick={() => addMockToast('info', 'Primary CTA triggered')} className="px-4 py-2 text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/30 flex items-center gap-2 active:scale-98 cursor-pointer">
                    <Plus className="w-4 h-4" />
                    Primary Action
                  </button>

                  <button onClick={() => addMockToast('info', 'Secondary button clicked')} className="px-4 py-2 text-xs font-semibold bg-gray-100 hover:bg-gray-200 dark:bg-slate-900 dark:hover:bg-slate-805 text-gray-900 dark:text-white rounded-lg transition-all focus:outline-none cursor-pointer">
                    Secondary Dark
                  </button>

                  <button onClick={() => addMockToast('info', 'Neutral outline click')} className="px-4 py-2 text-xs font-semibold border border-gray-250 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-905 text-gray-700 dark:text-slate-300 rounded-lg transition-all cursor-pointer">
                    Outline Gray
                  </button>

                  <button onClick={() => addMockToast('error', 'Destructive warning activated')} className="px-4 py-2 text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white rounded-lg shadow-sm transition-all flex items-center gap-2 cursor-pointer">
                    <Trash2 className="w-3.5 h-3.5" />
                    Destructive Action
                  </button>

                  <button onClick={() => addMockToast('success', 'Ghost link clicked')} className="px-4 py-2 text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/20 rounded-lg transition-all cursor-pointer">
                    Ghost Link Button
                  </button>
                </div>
              </div>

              {/* STATES SPEC CARD */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-6 rounded-2xl shadow-xs space-y-6 text-left">
                <div>
                  <h3 className="text-xs font-bold text-gray-400 dark:text-slate-500 uppercase tracking-widest font-mono">Component States</h3>
                  <p className="text-xs text-gray-500 mt-1">{isRu ? 'Интерактивные состояния: загрузка, деактивация, активный пульс' : 'Active state simulations'}</p>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  {/* Disabled input */}
                  <button disabled className="px-4 py-2 text-xs font-bold bg-gray-100 dark:bg-slate-900 text-gray-400 dark:text-slate-600 border border-gray-200 dark:border-slate-800 rounded-lg cursor-not-allowed">
                    🚫 Disabled Button
                  </button>

                  {/* Loading spinning state */}
                  <button
                    onClick={() => {
                      setMockLoadingState(true);
                      setTimeout(() => setMockLoadingState(false), 2500);
                    }}
                    className="px-4 py-2 text-xs font-bold bg-indigo-600 text-white rounded-lg transition-all flex items-center gap-2 cursor-pointer whitespace-nowrap"
                  >
                    {mockLoadingState ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                    ) : (
                      <Zap className="w-3.5 h-3.5" />
                    )}
                    <span>{mockLoadingState ? (isRu ? 'Запуск...' : 'Spinning Live...') : (isRu ? 'Нажми Загрузку' : 'Run Loader')}</span>
                  </button>

                  {/* Ping heartbeat glow action */}
                  <button className="relative px-3.5 py-2 text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg shadow-[0_0_15px_rgba(16,185,129,0.25)] transition-all flex items-center gap-1.5 cursor-pointer">
                    <span className="flex h-1.5 w-1.5 relative">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-300"></span>
                    </span>
                    <span>Live Beacon</span>
                  </button>

                  {/* Simple icon action square button */}
                  <button onClick={() => addMockToast('info', 'Utility shortcut opened')} className="p-2 border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-gray-600 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white rounded-lg transition-all cursor-pointer">
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
              </div>

            </div>
          </section>
        )}

        {/* SECTION B: SYSTEM INPUTS, FORMS AND INTERACTIVE CONTROLS */}
        {(activeSection === 'all' || activeSection === 'components') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-violet-500/10 rounded-lg text-violet-500">
                <SlidersHorizontal className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '2. Поля Ввода, Формы и Переключатели' : '2. Form Input fields & Toggles'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Поля конфигурации весов, скрытие секретов, селекторы параметров и переключатели.' : 'Unified form fields, secrets masking, radio grids, and range sliders.'}
                </p>
              </div>
            </div>

            <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-2xl p-6 md:p-8 space-y-8 text-left">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

                {/* STANDARD PARAMETER INPUT */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-gray-700 dark:text-slate-300 flex items-center gap-1.5">
                    <span>{isRu ? 'Абсолютный Хост Релиза' : 'Destination Cluster FQDN'}</span>
                    <HelpCircle className="w-3.5 h-3.5 text-gray-400 hover:text-gray-700 dark:hover:text-white cursor-help" />
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-gray-400">
                      <Terminal className="w-3.5 h-3.5" />
                    </div>
                    <input
                      type="text"
                      defaultValue="k8s.cluster-london.aws.internal"
                      className="w-full pl-9 pr-3 py-2 text-xs border border-gray-250 dark:border-slate-800 rounded-lg bg-gray-50/50 dark:bg-slate-900 text-gray-900 dark:text-white selection:bg-indigo-305 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 transition-all shadow-xs"
                    />
                  </div>
                  <span className="text-[10px] text-gray-400 block">{isRu ? 'Используется для межкластерного DNS' : 'Must map to standard private subnets'}</span>
                </div>

                {/* API KEY SECRETS FIELD WITH EYE SELECTOR */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-gray-700 dark:text-slate-300 flex items-center justify-between">
                    <span>{isRu ? 'Защищенный Токен Доступа' : 'Secured API Token key'}</span>
                    <span className="text-[9px] text-indigo-500 uppercase font-mono font-bold flex items-center gap-1">
                      <Lock className="w-2.5 h-2.5" /> AES-256
                    </span>
                  </label>
                  <div className="relative">
                    <input
                      type={apiKeyVisible ? 'text' : 'password'}
                      defaultValue="sk-gemini-83fjdka92m3kdf90011aX"
                      className="w-full pl-3 pr-9 py-2 text-xs font-mono border border-gray-250 dark:border-slate-800 rounded-lg bg-gray-50/50 dark:bg-slate-900 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 transition-all shadow-xs"
                    />
                    <button
                      onClick={() => setApiKeyVisible(!apiKeyVisible)}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-450 hover:text-gray-900 dark:hover:text-white"
                    >
                      {apiKeyVisible ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  <span className="text-[10px] text-gray-400 block">{isRu ? 'Кликните на иконку просмотра глаза' : 'Click the eye vector icon to toggle visibility'}</span>
                </div>

                {/* CUSTOM SELECT DROPDOWN */}
                <div className="space-y-1.5 relative">
                  <label className="text-xs font-bold text-gray-700 dark:text-slate-300">
                    {isRu ? 'Хостинг-Провайдер ноды' : 'Physic hosting rack'}
                  </label>

                  <div className="relative">
                    <button
                      onClick={() => setShowDropdownMock(!showDropdownMock)}
                      className="w-full flex items-center justify-between px-3 py-2 text-xs border border-gray-250 dark:border-slate-800 rounded-lg bg-gray-50/50 dark:bg-slate-900 text-gray-900 dark:text-white text-left focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-all cursor-pointer"
                    >
                      <span className="font-mono">{selectedDropdownOption}</span>
                      <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
                    </button>

                    {/* Simulating dropdown selection */}
                    {showDropdownMock && (
                      <div className="absolute right-0 left-0 mt-1 z-30 bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-lg shadow-lg py-1 overflow-hidden">
                        {[
                          { val: 'eu-west-1', label: 'AWS Ireland (eu-west-1)' },
                          { val: 'us-central-1', label: 'GCP Iowa (us-central-1)' },
                          { val: 'asia-east-2', label: 'Azure Hong Kong (asia-east-2)' }
                        ].map((opt) => (
                          <button
                            key={opt.val}
                            onClick={() => {
                              setSelectedDropdownOption(opt.val);
                              setShowDropdownMock(false);
                              addMockToast('success', `Switched routing server destination to: ${opt.label}`);
                            }}
                            className="w-full text-left px-3 py-1.5 text-xs hover:bg-indigo-50 dark:hover:bg-indigo-950/20 text-gray-800 dark:text-slate-300 flex items-center justify-between"
                          >
                            <span>{opt.label}</span>
                            {selectedDropdownOption === opt.val && <Check className="w-3 h-3 text-indigo-500" />}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] text-gray-400 block">{isRu ? 'Интерактивный список замен' : 'Simulated fully functioning selects'}</span>
                </div>

              </div>

              {/* SECOND ROW TOGGLES AND CHECKS */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-6 border-t border-gray-100 dark:border-slate-800/60">

                {/* TOGGLE SWITCH ELEMENT */}
                <div className="space-y-3">
                  <span className="text-xs font-bold text-gray-700 dark:text-slate-300 block">{isRu ? 'Микро-переключатель статуса' : 'Binary switch rule'}</span>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => {
                        setToggleVal(!toggleVal);
                        addMockToast('info', `HPA scaling limits toggled to ${!toggleVal ? 'ENABLED' : 'DISABLED'}`);
                      }}
                      className={`w-10 h-5.5 rounded-full p-0.5 transition-colors relative cursor-pointer ${toggleVal ? 'bg-indigo-650' : 'bg-gray-250 dark:bg-slate-800'}`}
                    >
                      <div className={`w-4.5 h-4.5 bg-white rounded-full shadow-xs transition-transform transform ${toggleVal ? 'translate-x-4.5' : 'translate-x-0'}`} />
                    </button>
                    <span className="text-xs text-gray-800 dark:text-slate-300">
                      {toggleVal ? (isRu ? 'Включено (Второй кластер)' : 'Active (Multi-region fallback)') : (isRu ? 'Выключено' : 'Disabled (Force node local)')}
                    </span>
                  </div>
                  <p className="text-[10px] text-gray-400 pr-5">{isRu ? 'Используется для триггера авто-скэйлинга' : 'Active global load shifts.'}</p>
                </div>

                {/* SOLID CHECKBOX ELEMENT */}
                <div className="space-y-3">
                  <span className="text-xs font-bold text-gray-700 dark:text-slate-300 block">{isRu ? 'Чекбоксы согласования' : 'Selection Checkboxes'}</span>
                  <label className="flex items-start gap-2.5 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={checkboxVal}
                      onChange={() => setCheckboxVal(!checkboxVal)}
                      className="sr-only"
                    />
                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all mt-0.5 ${
                      checkboxVal
                        ? 'bg-indigo-600 border-indigo-650 text-white shadow-xs'
                        : 'border-gray-255 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900 text-transparent'
                    }`}>
                      <Check className="w-3 h-3 stroke-[3]" />
                    </div>
                    <div className="flex flex-col text-left">
                      <span className="text-xs text-gray-800 dark:text-slate-350 font-bold">{isRu ? 'Записать в системный аудит' : 'Record audit metadata'}</span>
                      <span className="text-[10px] text-gray-400">{isRu ? 'Логирует и сохраняет в Firestore' : 'Required for deployment pipelines'}</span>
                    </div>
                  </label>
                </div>

                {/* RADIO BUTTON GROUP CARDS */}
                <div className="space-y-2.5">
                  <span className="text-xs font-bold text-gray-700 dark:text-slate-300 block">{isRu ? 'Выбор типа ускорителя GPU' : 'Accelerator instance slice'}</span>
                  <div className="space-y-2">
                    {[
                      { id: 'h100', name: 'NVIDIA H100 PCIe', desc: '80GB VRAM, extreme throughput' },
                      { id: 'a100', name: 'NVIDIA A100 SXM', desc: '40GB VRAM, standard inference' }
                    ].map((g) => (
                      <label
                        key={g.id}
                        onClick={() => setRadioVal(g.id as any)}
                        className={`flex items-center justify-between p-2.5 border rounded-lg cursor-pointer transition-all ${
                          radioVal === g.id
                            ? 'border-indigo-600 bg-indigo-50/30 dark:bg-indigo-950/20'
                            : 'border-gray-200 dark:border-slate-850 hover:bg-gray-50 dark:hover:bg-slate-905'
                        }`}
                      >
                        <div className="flex flex-col text-left">
                          <span className="text-xs font-bold text-gray-800 dark:text-gray-200">{g.name}</span>
                          <span className="text-[10px] text-gray-400">{g.desc}</span>
                        </div>
                        <div className={`w-4 h-4 rounded-full border flex items-center justify-center ${radioVal === g.id ? 'border-indigo-600' : 'border-gray-300 dark:border-slate-800'}`}>
                          {radioVal === g.id && <div className="w-2 h-2 rounded-full bg-indigo-600" />}
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

              </div>

            </div>
          </section>
        )}

        {/* SECTION C: COMPREHENSIVE DATA TABLES */}
        {(activeSection === 'all' || activeSection === 'components') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-emerald-500/10 rounded-lg text-emerald-500">
                <FolderOpen className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '3. Спецификация Таблиц и Массивов Данных' : '3. Deep Tabular & Metadata views'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Внешний вид системных отчетов, лимитов, разделителей и ячеек с действиями.' : 'Comprehensive table representations with badges, active configurations and metadata rows.'}
                </p>
              </div>
            </div>

            <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-2xl shadow-xs overflow-hidden">
              <div className="p-4 border-b border-gray-200 dark:border-slate-800 bg-gray-50/40 dark:bg-slate-950 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 bg-emerald-500 rounded-full" />
                  <span className="text-xs font-bold text-gray-800 dark:text-white">{isRu ? 'Логи ревизий балансировщика трафика' : 'Simulated Traffic Route Mapping'}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="px-2 py-0.5 text-[10px] font-mono bg-indigo-50 dark:bg-indigo-950/20 text-indigo-700 dark:text-indigo-400 rounded">
                    Total rows: 3 stable
                  </span>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-slate-800 text-xs font-bold text-gray-450 dark:text-slate-500 uppercase divide-x divide-gray-100 dark:divide-slate-850 bg-gray-50/30 dark:bg-slate-950/20">
                      <th className="p-3.5 pl-6">{isRu ? 'Вес (Weight)' : 'Deployment Destination'}</th>
                      <th className="p-3.5">{isRu ? 'Отказоустойчивость' : 'Rate Limit (RPM)'}</th>
                      <th className="p-3.5">{isRu ? 'Задержка P99' : 'P99 Latency'}</th>
                      <th className="p-3.5">{isRu ? 'Плитка статуса' : 'System Aura Health'}</th>
                      <th className="p-3.5 pr-6 text-right">{isRu ? 'Шестерня' : 'Actions Control'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-slate-850 text-xs">

                    {/* Row 1 */}
                    <tr className="hover:bg-gray-50/30 dark:hover:bg-slate-905 transition-colors">
                      <td className="p-3.5 pl-6">
                        <div className="flex items-center gap-3">
                          <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-200/20 flex items-center justify-center font-bold font-mono text-indigo-600 dark:text-indigo-400">
                            A
                          </div>
                          <div className="flex flex-col text-left">
                            <span className="font-bold text-gray-900 dark:text-gray-200">gemini-2.5-pro-v1</span>
                            <span className="text-[10px] text-gray-400">Target host: weight 80%</span>
                          </div>
                        </div>
                      </td>
                      <td className="p-3.5">
                        <div className="font-mono text-gray-700 dark:text-slate-350">
                          10,000 RPM
                        </div>
                      </td>
                      <td className="p-3.5 text-gray-600 dark:text-slate-400">
                        125 ms
                      </td>
                      <td className="p-3.5">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200/20 text-emerald-700 dark:text-emerald-400 font-bold uppercase text-[9px] tracking-wider">
                          <CheckCircle2 className="w-2.5 h-2.5" /> Stable
                        </span>
                      </td>
                      <td className="p-3.5 pr-6 text-right">
                        <button onClick={() => addMockToast('success', 'Opened advanced settings for Route A')} className="text-gray-400 hover:text-indigo-500 p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-900 cursor-pointer">
                          <MoreVertical className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>

                    {/* Row 2 */}
                    <tr className="hover:bg-gray-50/30 dark:hover:bg-slate-905 transition-colors">
                      <td className="p-3.5 pl-6">
                        <div className="flex items-center gap-3">
                          <div className="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-955/30 border border-amber-200/20 flex items-center justify-center font-bold font-mono text-amber-600 dark:text-amber-400">
                            B
                          </div>
                          <div className="flex flex-col text-left">
                            <span className="font-bold text-gray-950 dark:text-gray-200">gemini-2.5-flash-canary</span>
                            <span className="text-[10px] text-gray-400">Target host: weight 15%</span>
                          </div>
                        </div>
                      </td>
                      <td className="p-3.5">
                        <div className="font-mono text-gray-700 dark:text-slate-405">
                          1,500 RPM
                        </div>
                      </td>
                      <td className="p-3.5 text-gray-600 dark:text-slate-400">
                        45 ms
                      </td>
                      <td className="p-3.5">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-50 dark:bg-amber-950/20 border border-amber-200/20 text-amber-700 dark:text-amber-400 font-bold uppercase text-[9px] tracking-wider">
                          <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" /> Testing
                        </span>
                      </td>
                      <td className="p-3.5 pr-6 text-right">
                        <button onClick={() => addMockToast('success', 'Opened advanced settings for Route B')} className="text-gray-400 hover:text-indigo-500 p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-900 cursor-pointer">
                          <MoreVertical className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>

                    {/* Row 3 */}
                    <tr className="hover:bg-gray-50/30 dark:hover:bg-slate-905 transition-colors">
                      <td className="p-3.5 pl-6">
                        <div className="flex items-center gap-3">
                          <div className="w-7 h-7 rounded-lg bg-rose-50 dark:bg-rose-955/30 border border-rose-200/20 flex items-center justify-center font-bold font-mono text-rose-600 dark:text-rose-400">
                            C
                          </div>
                          <div className="flex flex-col text-left">
                            <span className="font-bold text-gray-900 dark:text-gray-200">fine-tuned-legacy-v2</span>
                            <span className="text-[10px] text-gray-400">Target host: weight 5%</span>
                          </div>
                        </div>
                      </td>
                      <td className="p-3.5">
                        <div className="font-mono text-gray-700 dark:text-slate-350">
                          400 RPM
                        </div>
                      </td>
                      <td className="p-3.5 text-gray-600 dark:text-slate-400">
                        890 ms (throttled)
                      </td>
                      <td className="p-3.5">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-rose-50 dark:bg-rose-950/20 border border-rose-200/20 text-rose-700 dark:text-rose-400 font-bold uppercase text-[9px] tracking-wider animate-pulse">
                          <AlertTriangle className="w-2.5 h-2.5" /> High load
                        </span>
                      </td>
                      <td className="p-3.5 pr-6 text-right">
                        <button onClick={() => addMockToast('success', 'Opened advanced settings for Route C')} className="text-gray-400 hover:text-indigo-500 p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-900 cursor-pointer">
                          <MoreVertical className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>

                  </tbody>
                </table>
              </div>

            </div>
          </section>
        )}

        {/* SECTION D: NOTIFICATIONS, ALERTS AND LOADING SHIMMERS */}
        {(activeSection === 'all' || activeSection === 'components') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-amber-500/10 rounded-lg text-amber-500">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '4. Системные Оповещения и Анимации Загрузки' : '4. System Alerts & Skeleton shimmers'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Информационные блоки предупреждений и плавные макеты загрузки нод.' : 'Visual representations of warning screens, info banners, and loading shimmers.'}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

              {/* ALERTS DEMO CARD */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-6 rounded-2xl shadow-xs space-y-4 text-left">
                <h3 className="text-xs font-bold text-gray-400 dark:text-slate-500 uppercase tracking-widest font-mono">Feedback Alert banners</h3>

                {/* Info banner */}
                <div className="flex gap-3 p-3.5 rounded-xl bg-indigo-50/60 dark:bg-indigo-950/15 border border-indigo-100 dark:border-indigo-900/35">
                  <Info className="w-5 h-5 text-indigo-500 flex-shrink-0" />
                  <div className="space-y-0.5">
                    <span className="text-xs font-semibold text-indigo-900 dark:text-indigo-400">{isRu ? 'Системное Квотирование' : 'System Quotas Update'}</span>
                    <p className="text-[11px] text-indigo-700/80 dark:text-indigo-300/80 leading-relaxed">
                      {isRu ? 'Лимиты запросов на веса будут заблокированы при достижении RPM > 12тыс.' : 'Prometheus rules require all custom routes to utilize structured API tags.'}
                    </p>
                  </div>
                </div>

                {/* Warning Alert banner */}
                <div className="flex gap-3 p-3.5 rounded-xl bg-amber-50 dark:bg-amber-955/10 border border-amber-200/40 dark:border-amber-900/30">
                  <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0" />
                  <div className="space-y-0.5">
                    <span className="text-xs font-bold text-amber-850 dark:text-amber-400">{isRu ? 'Обнаружен перекос реплик' : 'Unbalanced Pod Partition'}</span>
                    <p className="text-[11px] text-amber-800/85 dark:text-amber-300/80 leading-relaxed">
                      {isRu ? 'Некоторые поды не завершили статус деплоймента. Весы могут частично игнорироваться.' : 'Pod auto-scaling scaled down to 1 active replica in the EU deployment zones.'}
                    </p>
                  </div>
                </div>
              </div>

              {/* SKELETON LOADERS SQUEEZE */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-6 rounded-2xl shadow-xs space-y-4 text-left">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-gray-400 dark:text-slate-500 uppercase tracking-widest font-mono">Skeleton Loading shimmers</h3>
                  <span className="text-[10px] text-indigo-500 font-mono font-bold animate-pulse">Shimmer FX ON</span>
                </div>

                <div className="space-y-3.5 pt-2">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-full bg-gray-200 dark:bg-slate-900 animate-pulse flex-shrink-0" />
                    <div className="flex-1 space-y-2">
                      <div className="h-3.5 bg-gray-200 dark:bg-slate-900 rounded-md w-1/3 animate-pulse" />
                      <div className="h-2.5 bg-gray-150 dark:bg-slate-905 rounded-md w-2/3 animate-pulse" />
                    </div>
                  </div>

                  <div className="space-y-2.5 pt-3 border-t border-gray-100 dark:border-slate-800/50">
                    <div className="h-3 bg-gray-200 dark:bg-slate-900 rounded-md w-full animate-pulse" />
                    <div className="h-3 bg-gray-200 dark:bg-slate-900 rounded-md w-5/6 animate-pulse" />
                  </div>
                </div>
              </div>

            </div>
          </section>
        )}

        {/* SECTION E: MODAL VIEWPORTS AND POPUPS OVERLAYS */}
        {(activeSection === 'all' || activeSection === 'components') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-indigo-500/10 rounded-lg text-indigo-500">
                <Sliders className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '5. Системные Модальные Окна и Оверлеи' : '5. Dialog Box & Modal Viewport overlays'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Поддержка всплывающих предупреждений и форм создания новых ключей.' : 'Standard viewport layouts built with high-fidelity margins and rounded borders.'}
                </p>
              </div>
            </div>

            <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-2xl p-6 md:p-8 text-center space-y-4">
              <div className="max-w-md mx-auto space-y-3">
                <span className="text-[10px] font-mono tracking-widest text-indigo-500 uppercase font-bold">{isRu ? 'Пример интеграции диалогов' : 'Viewport Overlay triggers'}</span>
                <p className="text-xs text-gray-500">{isRu ? 'Нажмите на кнопку ниже, чтобы открыть полноразмерную интерактивную симуляцию модального окна.' : 'Open a beautiful mock overlay modal window complete with dark backing layer'}</p>

                <button
                  onClick={() => setShowModalMock(true)}
                  className="px-5 py-2.5 text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg shadow-sm transition-all inline-flex items-center gap-2 cursor-pointer active:scale-98"
                >
                  <ExternalLink className="w-4 h-4" />
                  <span>{isRu ? 'Запустить Модалку' : 'Open Demo Modal Window'}</span>
                </button>
              </div>

              {/* MODAL SIMULATION PORTAL */}
              <AnimatePresence>
                {showModalMock && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
                    <motion.div
                      initial={{ scale: 0.95, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0.95, opacity: 0 }}
                      className="w-full max-w-md border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-2xl shadow-xl overflow-hidden text-left"
                    >
                      <div className="p-5 border-b border-gray-200 dark:border-slate-800 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Cpu className="w-5 h-5 text-indigo-500" />
                          <span className="text-sm font-bold text-gray-950 dark:text-white">
                            {isRu ? 'Конфигурирование Подов Релиза' : 'System Deployment Specs'}
                          </span>
                        </div>
                        <button
                          onClick={() => setShowModalMock(false)}
                          className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-900 hover:text-gray-900 dark:hover:text-white transition-all cursor-pointer"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>

                      <div className="p-5 space-y-4">
                        <div className="p-3 bg-indigo-50/60 dark:bg-indigo-950/20 rounded-xl border border-indigo-200/20 text-xs text-indigo-800 dark:text-indigo-400 leading-relaxed">
                          {isRu ? 'Внимание! Изменение весов приведет к автоматическому перезапуску текущего Prometheus роутера в кластере.' : 'Tweak dynamic parameter configs inside this sandboxed container.'}
                        </div>

                        <div className="space-y-1.5">
                          <label className="text-xs font-bold text-gray-700 dark:text-slate-350">{isRu ? 'Нода назначения' : 'Replica Zone target'}</label>
                          <input type="text" readOnly defaultValue="h100-rack-3-london" className="w-full px-3 py-2 text-xs border border-gray-200 dark:border-slate-800 rounded-lg bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white font-mono" />
                        </div>

                        <div className="space-y-1.5">
                          <label className="text-xs font-bold text-gray-700 dark:text-slate-350">{isRu ? 'Метрика RPM Лимита' : 'Limit Quota RPM threshold'}</label>
                          <select className="w-full px-3 py-2 text-xs border border-gray-200 dark:border-slate-800 rounded-lg bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-white">
                            <option>10,000 requests per minute</option>
                            <option>5,000 requests per minute</option>
                            <option>Uncapped unlimited</option>
                          </select>
                        </div>
                      </div>

                      <div className="p-5 border-t border-gray-200 dark:border-slate-800 bg-gray-50/40 dark:bg-slate-950/20 flex items-center justify-end gap-3">
                        <button
                          onClick={() => setShowModalMock(false)}
                          className="px-4 py-2 rounded-lg text-xs font-semibold text-gray-650 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-900 cursor-pointer"
                        >
                          {isRu ? 'Отмена' : 'Cancel'}
                        </button>
                        <button
                          onClick={() => {
                            setShowModalMock(false);
                            addMockToast('success', 'Replica Zone rules deployed to AWS live cluster!');
                          }}
                          className="px-4 py-2 rounded-lg text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm cursor-pointer"
                        >
                          {isRu ? 'Сохранить и задеплоить' : 'Apply deployment weights'}
                        </button>
                      </div>

                    </motion.div>
                  </div>
                )}
              </AnimatePresence>

            </div>
          </section>
        )}

        {/* SECTION F: HEXADECIMAL COLORS & DESIGN PRINCIPLES */}
        {(activeSection === 'all' || activeSection === 'colors') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-indigo-500/10 rounded-lg text-indigo-500">
                <Palette className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '6. Истинная Цветовая Спецификация' : '6. Complete Hex Palette & Core Theme'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Проверенные контрастные оттенки для светлого и космического темного оформления.' : 'Validated hex values matching Tailwind and CSS layouts.'}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">

              {/* PRIMARY COLD SLATE */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-xl overflow-hidden shadow-xs p-4 space-y-3 text-left">
                <div className="h-16 w-full rounded-lg bg-slate-900 flex items-end p-2 border border-slate-800 shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]">
                  <span className="font-mono text-[10px] text-slate-400">#0f172a</span>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-gray-950 dark:text-white">Slate 900</h4>
                  <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                    {isRu ? 'Основной фон темного режима' : 'Global dark mode background'}
                  </p>
                </div>
              </div>

              {/* COSMIC DARK CARDS */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-xl overflow-hidden shadow-xs p-4 space-y-3 text-left">
                <div className="h-16 w-full rounded-lg bg-[#020617] flex items-end p-2 border border-slate-950">
                  <span className="font-mono text-[10px] text-slate-400">#020617</span>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-gray-950 dark:text-white">Slate 950</h4>
                  <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                    {isRu ? 'Задняя подложка сайдбара и окон' : 'Cards and side navigation layers'}
                  </p>
                </div>
              </div>

              {/* CHROME BORDERS */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-xl overflow-hidden shadow-xs p-4 space-y-3 text-left">
                <div className="h-16 w-full rounded-lg bg-white dark:bg-slate-850 flex items-center justify-center p-2 border border-gray-150 dark:border-slate-800">
                  <span className="font-mono text-[10px] text-gray-500 dark:text-slate-400">Border Light/Dark</span>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-gray-950 dark:text-white">Borders</h4>
                  <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                    {isRu ? 'Светлый: gray-200, Темный: slate-800' : 'Gray-200 Light / Slate-800 Dark'}
                  </p>
                </div>
              </div>

              {/* BRAND INDIGO */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-xl overflow-hidden shadow-xs p-4 space-y-3 text-left">
                <div className="h-16 w-full rounded-lg bg-indigo-600 flex items-end p-2">
                  <span className="font-mono text-[10px] text-white">#4f46e5</span>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-gray-950 dark:text-white">Indigo 600</h4>
                  <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                    {isRu ? 'Основной бренд-акцент кнопок' : 'Primary branding active state'}
                  </p>
                </div>
              </div>

            </div>
          </section>
        )}

        {/* SECTION G: TYPOGRAPHY SPECIFICATION */}
        {(activeSection === 'all' || activeSection === 'typography') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-violet-500/10 rounded-lg text-violet-500">
                <Type className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '7. Спецификация Шрифтов и Иерархии' : '7. Font Pairings & Type Scaler'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Отношение текстовых пропорций Inter (интерфейсный) и JetBrains Mono (технический).' : 'Detailed hierarchy pairing Inter for layouts with JetBrains Mono for system log lines.'}
                </p>
              </div>
            </div>

            <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-6 rounded-2xl shadow-xs space-y-6 text-left">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-start border-b border-gray-100 dark:border-slate-850 pb-6">
                <div className="space-y-1">
                  <span className="text-xs font-mono font-bold text-indigo-500">Display Title</span>
                  <p className="text-[10px] text-gray-400">font-extrabold tracking-tight</p>
                </div>
                <div className="md:col-span-3">
                  <h1 className="text-3xl font-extrabold tracking-tight text-gray-950 dark:text-white">
                    {isRu ? '3.5B параметров вычислены' : 'The quick brown fox jumps'}
                  </h1>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-start border-b border-gray-100 dark:border-slate-850 pb-6">
                <div className="space-y-1">
                  <span className="text-xs font-mono font-bold text-indigo-500">Subtitle Element</span>
                  <p className="text-[10px] text-gray-400">font-semibold tracking-tight</p>
                </div>
                <div className="md:col-span-3">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-200">
                    {isRu ? 'Детализация технических весов кнопок' : 'Detailed performance tracking logs'}
                  </h3>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-start">
                <div className="space-y-1">
                  <span className="text-xs font-mono font-bold text-indigo-500">Log terminal Mono</span>
                  <p className="text-[10px] text-gray-400">font-mono text-xs</p>
                </div>
                <div className="md:col-span-3 bg-gray-50 dark:bg-slate-900 p-4 rounded-xl border border-gray-200/60 dark:border-slate-800">
                  <pre className="font-mono text-xs text-indigo-650 dark:text-indigo-400 leading-relaxed overflow-x-auto">
{`$ telemetry-probe --probe-mode=detailed
[OK] Core components verified. Design system values compiled.
[METRIC] SYS_BORDER_RADIUS_VAL: 12px (rounded-xl)
[METRIC] CSS_VAR_ACTIVE_GLOW_HEX: #4f46e5 (indigo)`}
                  </pre>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* SECTION H: INTERACTIVE EXPERIMENT PLAYGROUND */}
        {(activeSection === 'all' || activeSection === 'sandbox') && (
          <section className="space-y-6">
            <div className="flex items-center gap-3 border-b border-gray-200 dark:border-slate-800 pb-3">
              <div className="p-1.5 bg-indigo-500/10 rounded-lg text-indigo-500">
                <Terminal className="w-5 h-5" />
              </div>
              <div className="text-left">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">
                  {isRu ? '8. Интерактивная Творческая Песочница' : '8. Interactive Creative Design Sandbox'}
                </h2>
                <p className="text-xs text-gray-500 dark:text-slate-400">
                  {isRu ? 'Меняйте стили, масштабируйте реплики и исследуйте адаптивность системы.' : 'Adjust dynamic attributes of variables inside this real-time render bento cage.'}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-stretch">

              {/* CONTROLS CANE */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-6 rounded-2xl shadow-xs space-y-6 md:col-span-1 text-left">
                <h3 className="text-sm font-bold text-gray-950 dark:text-white border-b border-gray-100 dark:border-slate-800/80 pb-3 flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-indigo-500" />
                  <span>{isRu ? 'Модификаторы дизайна' : 'Aura Modifiers'}</span>
                </h3>

                {/* Theme colors selector */}
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-gray-750 dark:text-slate-350">{isRu ? 'Цветовой пресет бренда' : 'Brand Aura Accent'}</span>
                  <div className="grid grid-cols-2 gap-2">
                    {(['indigo', 'emerald', 'amber', 'rose'] as const).map((color) => (
                      <button
                        key={color}
                        onClick={() => {
                          setSandboxTheme(color);
                          addMockToast('info', `Simulated theme accent shift to: ${color}`);
                        }}
                        className={`py-1.5 rounded-lg text-[10px] font-bold capitalize border transition-all ${
                          sandboxTheme === color
                            ? themeColors[color].fill + ' border-transparent scale-102 shadow-xs'
                            : 'border-gray-250 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-900 text-gray-700 dark:text-slate-400 cursor-pointer'
                        }`}
                      >
                        {color}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Range sliders */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span className="text-gray-700 dark:text-slate-350">{isRu ? 'Реплики подов' : 'Scale Replicas'}</span>
                    <span className="font-mono text-indigo-650 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/20 px-2 py-0.5 rounded">
                      {sandboxReplicas} / 8
                    </span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={8}
                    value={sandboxReplicas}
                    onChange={(e) => setSandboxReplicas(Number(e.target.value))}
                    className="w-full accent-indigo-600 h-1.5 bg-gray-200 dark:bg-slate-800 rounded-lg cursor-ew-resize"
                  />
                </div>

                {/* State pulse */}
                <div className="flex items-center justify-between border-t border-gray-100 dark:border-slate-850 pt-4">
                  <span className="text-xs font-semibold text-gray-750 dark:text-slate-350">{isRu ? 'Пульс индикатора' : 'Visual pulse aura'}</span>
                  <button
                    onClick={() => setIsSandboxPulsing(!isSandboxPulsing)}
                    className={`w-9 h-5 rounded-full p-0.5 transition-all relative cursor-pointer ${isSandboxPulsing ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-slate-800'}`}
                  >
                    <div className={`w-4 h-4 bg-white rounded-full shadow-xs transition-all transform ${isSandboxPulsing ? 'translate-x-4' : 'translate-x-0'}`} />
                  </button>
                </div>
              </div>

              {/* RENDER VIEW CARD */}
              <div className="border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-6 rounded-2xl shadow-xs md:col-span-2 flex flex-col justify-between space-y-6 text-left">
                <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-850 pb-3">
                  <div className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${
                      sandboxStatus === 'ready' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'
                    }`} />
                    <span className="text-xs font-bold text-gray-950 dark:text-white uppercase tracking-wider font-mono">
                      {isRu ? 'Интерактивная карта системы' : 'Interactive System Spec Node'}
                    </span>
                  </div>
                </div>

                <div className="flex-1 flex items-center justify-center p-4 bg-gray-50/50 dark:bg-slate-905 border border-dashed border-gray-200 dark:border-slate-850 rounded-xl">
                  <div className="w-full max-w-sm border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-xl p-5 shadow-xs relative overflow-hidden transition-all duration-300">
                    <div className={`absolute right-0 top-0 -mr-12 -mt-12 w-28 h-28 ${themeColors[sandboxTheme].bg} rounded-full blur-2xl pointer-events-none transition-all duration-300`} />

                    <div className="flex items-center justify-between mb-3">
                      <span className={`px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-widest rounded ${themeColors[sandboxTheme].badge}`}>
                        {sandboxTheme} Theme Active
                      </span>
                      <span className="flex h-2.5 w-2.5 relative">
                        {isSandboxPulsing && (
                          <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                            sandboxTheme === 'indigo' ? 'bg-indigo-400' : sandboxTheme === 'emerald' ? 'bg-emerald-400' : sandboxTheme === 'amber' ? 'bg-amber-400' : 'bg-rose-450'
                          }`}></span>
                        )}
                        <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                          sandboxTheme === 'indigo' ? 'bg-indigo-500' : sandboxTheme === 'emerald' ? 'bg-emerald-500' : sandboxTheme === 'amber' ? 'bg-amber-500' : 'bg-rose-600'
                        }`}></span>
                      </span>
                    </div>

                    <h4 className="text-sm font-bold text-gray-950 dark:text-white">
                      {isRu ? 'Аналитическая Кабина' : 'Virtual Routing Instance'}
                    </h4>
                    <p className="text-[11px] text-gray-450 dark:text-slate-500 mt-1">
                      {isRu ? 'Отображение адаптивных весов на лету в реальном времени.' : 'Demonstrates active weights, status indicators and scale sliders.'}
                    </p>

                    <div className="mt-4 space-y-1.5">
                      <div className="flex justify-between text-[9px] font-mono font-bold text-gray-400 uppercase tracking-widest">
                        <span>{isRu ? 'Активные реплики' : 'Active Replicas'}</span>
                        <span>{sandboxReplicas} / 8</span>
                      </div>
                      <div className="flex h-7 gap-1">
                        {Array.from({ length: 8 }).map((_, i) => {
                          const isActive = i < sandboxReplicas;
                          return (
                            <div
                              key={i}
                              className={`h-full flex-1 rounded transition-all duration-300 ${
                                isActive
                                  ? sandboxTheme === 'indigo' ? 'bg-indigo-600' : sandboxTheme === 'emerald' ? 'bg-emerald-500' : sandboxTheme === 'amber' ? 'bg-amber-500' : 'bg-rose-600'
                                  : 'bg-gray-100 dark:bg-slate-900 border border-gray-200 dark:border-slate-800'
                              }`}
                            />
                          );
                        })}
                      </div>
                    </div>

                  </div>
                </div>

                <div className="bg-gray-50 dark:bg-slate-900/60 p-4 rounded-xl border border-gray-200 dark:border-slate-800">
                  <span className="text-[10px] font-bold text-gray-400 tracking-wider uppercase block mb-1">Exported JSX Specs</span>
                  <code className="text-[10px] font-mono text-indigo-650 dark:text-indigo-400 block whitespace-pre-wrap leading-tight">
{`<div className="flex h-7 gap-1">
  {Array.from({ length: 8 }).map((_, i) => (
    <div key={i} className={\`flex-1 rounded \${i < activeReplicas ? "bg-${sandboxTheme}-600" : "bg-gray-100 dark:bg-slate-900"}\`} />
  ))}
</div>`}
                  </code>
                </div>

              </div>

            </div>
          </section>
        )}

      </div>

      {/* FOOTER */}
      <div className="border-t border-gray-200 dark:border-slate-800 pt-8 text-center max-w-xl mx-auto space-y-2">
        <span className="text-[10px] font-mono font-bold text-indigo-500 uppercase tracking-[0.2em]">{isRu ? 'Дизайн во славу детерминизма' : 'Crafted strictly to specifications'}</span>
        <p className="text-xs text-gray-500 dark:text-slate-400 leading-relaxed">
          {isRu
            ? 'Спасибо за изучение нашей дизайн-системы! Все компоненты используют чистые селекторы Tailwind CSS, абсолютно детерминистичны и соответствуют высокой плотности данных.'
            : 'Every primitive uses Inter paired with JetBrains Mono for a highly clean, engineering-first aesthetic.'
          }
        </p>
      </div>

    </div>
  );
}
