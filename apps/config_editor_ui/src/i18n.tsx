import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export const SUPPORTED_LOCALES = ['ru', 'en'] as const;
export type Locale = typeof SUPPORTED_LOCALES[number];

export const translations = {
  ru: {
    navigation: { benchmarks: 'Бенчмарки', runs: 'Запуски', sources: 'Источники данных', strategies: 'Стратегии поиска', designSystem: 'Дизайн-система' },
    language: { russian: 'Русский (RU)', english: 'English (EN)', label: 'Язык интерфейса' },
    common: { cancel: 'Отмена', back: 'Назад', create: 'Создать', save: 'Сохранить', edit: 'Изменить', delete: 'Удалить', search: 'Поиск', all: 'Все', error: 'Ошибка', loading: 'Загружаем состояние бенчмарков…' },
  },
  en: {
    navigation: { benchmarks: 'Benchmarks', runs: 'Runs', sources: 'Data sources', strategies: 'Search strategies', designSystem: 'Design system' },
    language: { russian: 'Русский (RU)', english: 'English (EN)', label: 'Interface language' },
    common: { cancel: 'Cancel', back: 'Back', create: 'Create', save: 'Save', edit: 'Edit', delete: 'Delete', search: 'Search', all: 'All', error: 'Error', loading: 'Loading benchmark state…' },
  },
} as const;

export function resolveLocale(value: string | null | undefined): Locale { return value === 'en' ? 'en' : 'ru'; }
type I18nValue = { locale: Locale; setLocale(locale: Locale): void; t(ru: string, en: string): string };
const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }): JSX.Element {
  const [locale, setLocaleState] = useState<Locale>(() => resolveLocale(window.localStorage.getItem('db-benchmark-locale')));
  const setLocale = (next: Locale) => { window.localStorage.setItem('db-benchmark-locale', next); setLocaleState(next); };
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const value = useMemo<I18nValue>(() => ({ locale, setLocale, t: (ru, en) => locale === 'ru' ? ru : en }), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue { const value = useContext(I18nContext); if (!value) throw new Error('I18nProvider is required'); return value; }
