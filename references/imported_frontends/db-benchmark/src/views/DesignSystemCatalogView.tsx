import React, { useState } from 'react';
import {
  Palette,
  CheckCircle2,
  AlertTriangle,
  Play,
  Settings,
  Plus,
  Server,
  Database,
  Layers,
  Terminal,
  RefreshCw,
  Info,
} from 'lucide-react';
import {
  Button,
  StatusBadge,
  Input,
  Select,
  Modal,
  NoticeBanner,
} from '../components/ui/GpbComponents';
import { useBenchmark } from '../context/BenchmarkContext';

export const DesignSystemCatalogView: React.FC = () => {
  const { isDark, toggleTheme } = useBenchmark();
  const [demoModalOpen, setDemoModalOpen] = useState(false);
  const [inputText, setInputText] = useState('Значение параметра');
  const [inputError, setInputError] = useState('');
  const [selectVal, setSelectVal] = useState('clickhouse');

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <Palette className="w-5 h-5 text-[#0033A0] dark:text-[#78A9FF]" />
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Каталог дизайн-системы (@adqm/gpb-ui)
          </h1>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Эталонные компоненты пользовательского интерфейса в стиле консолей ACM/ADCM и корпоративной
          палитры ГПБ.
        </p>
      </div>

      <NoticeBanner type="info" title="Назначение каталога дизайн-системы (Раздел 15)">
        Каталог дизайн-системы — это вспомогательная витрина компонентов интерфейса, а не
        доказательство поддержки показанных в ней бизнес-возможностей. Все компоненты адаптированы
        для высокой информационной плотности и поддерживают как светлую, так и тёмную темы с
        сохранением точной геометрии.
      </NoticeBanner>

      {/* 1. Color Palette & Corporate GPB Tone */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-5 shadow-2xs space-y-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          1. Цветовая палитра и акценты
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="p-3 rounded border border-slate-200 dark:border-[#2A3442] bg-white dark:bg-[#1C232E] space-y-1.5">
            <div className="w-full h-8 rounded bg-[#0033A0] flex items-center justify-center text-white font-mono text-[10px] font-bold">
              #0033A0
            </div>
            <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
              GPB Primary Blue
            </div>
            <div className="text-[10px] text-slate-400">Основной корпоративный акцент</div>
          </div>

          <div className="p-3 rounded border border-slate-200 dark:border-[#2A3442] bg-white dark:bg-[#1C232E] space-y-1.5">
            <div className="w-full h-8 rounded bg-[#198038] flex items-center justify-center text-white font-mono text-[10px] font-bold">
              #198038
            </div>
            <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
              Success Green
            </div>
            <div className="text-[10px] text-slate-400">Готов, завершён, доступен</div>
          </div>

          <div className="p-3 rounded border border-slate-200 dark:border-[#2A3442] bg-white dark:bg-[#1C232E] space-y-1.5">
            <div className="w-full h-8 rounded bg-[#DA1E28] flex items-center justify-center text-white font-mono text-[10px] font-bold">
              #DA1E28
            </div>
            <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
              Danger / Error
            </div>
            <div className="text-[10px] text-slate-400">Ошибка, недоступен</div>
          </div>

          <div className="p-3 rounded border border-slate-200 dark:border-[#2A3442] bg-white dark:bg-[#1C232E] space-y-1.5">
            <div className="w-full h-8 rounded bg-[#F1C21B] flex items-center justify-center text-slate-950 font-mono text-[10px] font-bold">
              #F1C21B
            </div>
            <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
              Warning / Pending
            </div>
            <div className="text-[10px] text-slate-400">Не проверен, требует внимания</div>
          </div>
        </div>
      </div>

      {/* 2. Status Badges & Chips */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-5 shadow-2xs space-y-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          2. Индикаторы состояний (Status Badges)
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status="ready" label="Готов к запуску" />
          <StatusBadge status="completed" label="Завершён" />
          <StatusBadge status="running" label="Выполняется" />
          <StatusBadge status="not_checked" label="Не проверен" />
          <StatusBadge status="incomplete" label="Не настроен" />
          <StatusBadge status="unavailable" label="Недоступен" />
          <StatusBadge status="error" label="Ошибка" />
        </div>
      </div>

      {/* 3. Buttons */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-5 shadow-2xs space-y-4">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          3. Кнопки и действия
        </h2>

        <div className="space-y-2">
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
            Варианты (Variants):
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button variant="primary" icon={Plus}>
              Основное действие (Primary)
            </Button>
            <Button variant="secondary" icon={Settings}>
              Вторичное (Secondary)
            </Button>
            <Button variant="danger" icon={AlertTriangle}>
              Критическое (Danger)
            </Button>
            <Button variant="ghost">Отмена (Ghost)</Button>
            <Button variant="primary" isLoading>
              Загрузка...
            </Button>
            <Button variant="primary" disabled>
              Заблокировано
            </Button>
          </div>
        </div>

        <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-[#242C38]">
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
            Размеры (Sizes):
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button size="sm" variant="primary">
              Small (28px)
            </Button>
            <Button size="md" variant="primary">
              Medium (36px)
            </Button>
            <Button size="lg" variant="primary">
              Large (40px)
            </Button>
          </div>
        </div>
      </div>

      {/* 4. Form Controls */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-5 shadow-2xs space-y-4">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          4. Поля ввода и селекторы
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input
            label="Текстовое поле (Default)"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            helperText="Вспомогательная подпись для оператора"
          />

          <Input
            label="Поле с валидацией ошибки"
            value="некорректный_порт_999999"
            error="Порт должен быть в диапазоне 1..65535"
          />

          <Select
            label="Выпадающий список (Select)"
            value={selectVal}
            onChange={(e) => setSelectVal(e.target.value)}
          >
            <option value="clickhouse">ClickHouse (MergeTree Engine)</option>
            <option value="postgresql">PostgreSQL (Целевая архитектура)</option>
          </Select>

          <Input
            label="Заблокированное поле (Disabled)"
            disabled
            value="vault://secrets/infra/ch-ro-key"
          />
        </div>
      </div>

      {/* 5. Modal Window Demo */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded-md p-5 shadow-2xs space-y-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          5. Модальное окно (ADCM Style)
        </h2>
        <p className="text-xs text-slate-600 dark:text-slate-400">
          Модальные диалоги используются для добавления сущностей без ухода из основного контекста
          (например, добавление источника или пространства).
        </p>
        <Button variant="secondary" onClick={() => setDemoModalOpen(true)}>
          Открыть демонстрационное модальное окно
        </Button>
      </div>

      {/* Modal instance */}
      <Modal
        isOpen={demoModalOpen}
        onClose={() => setDemoModalOpen(false)}
        title="Демонстрация модального окна ADCM"
        subtitle="Образец корпоративного модального окна"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDemoModalOpen(false)}>
              Отмена
            </Button>
            <Button variant="primary" onClick={() => setDemoModalOpen(false)}>
              Подтвердить
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-xs text-slate-700 dark:text-slate-300">
          <p>
            Модальное окно содержит заголовок, краткое описание, прокручиваемую область содержимого и
            панель кнопок действий внизу.
          </p>
          <Input label="Параметр подтверждения" placeholder="Введите подтверждение..." />
        </div>
      </Modal>
    </div>
  );
};
