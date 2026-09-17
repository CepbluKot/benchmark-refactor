import type { ReactNode } from 'react';
import { ThemeProvider, ThemeSwitcher, useThemePreference } from '@adqm/gpb-ui';

export type ProductPage = 'sources' | 'benchmarks' | 'runs' | 'rule-banks';

const NAVIGATION: Array<{ id: ProductPage; label: string; hint: string; icon: string }> = [
  { id: 'sources', label: 'Источники данных', hint: 'Подключения ClickHouse', icon: '◌' },
  { id: 'benchmarks', label: 'Бенчмарки', hint: 'Конфигурации экспериментов', icon: '◇' },
  { id: 'runs', label: 'Запуски', hint: 'Измерения и кандидаты', icon: '◒' },
  { id: 'rule-banks', label: 'Банки правил', hint: 'Пространство поиска', icon: '▦' },
];

export function ProductShell({ page, onPageChange, children }: { page: ProductPage; onPageChange(page: ProductPage): void; children: ReactNode }): JSX.Element {
  const [theme, setTheme] = useThemePreference();
  const current = NAVIGATION.find((item) => item.id === page) ?? NAVIGATION[0];
  return (
    <ThemeProvider theme={theme} className="product-root">
      <div className="product-frame">
        <aside className="product-nav" aria-label="Основные разделы">
          <button type="button" className="product-logo" title="DDL Benchmark Engine" onClick={() => onPageChange('benchmarks')}><span>DB</span><strong>Benchmark<br />Studio</strong></button>
          <nav className="product-nav-list">
            {NAVIGATION.map((item) => (
              <button key={item.id} type="button" aria-current={page === item.id ? 'page' : undefined} className={`product-nav-item${page === item.id ? ' active' : ''}`} onClick={() => onPageChange(item.id)}>
                <span className="nav-glyph" aria-hidden="true">{item.icon}</span>
                <span><strong>{item.label}</strong><small>{item.hint}</small></span>
              </button>
            ))}
          </nav>
          <div className="product-nav-bottom"><span className="product-nav-bottom-label">ClickHouse plugin</span><span className="product-status-dot" title="Демо-режим" /></div>
        </aside>
        <main className="product-main">
          <header className="product-header">
            <div><h1>{current.label}</h1><p>Benchmark Studio / ClickHouse / {current.label}</p></div>
            <div className="product-header-actions"><span>Внутренний контур</span><ThemeSwitcher theme={theme} onThemeChange={setTheme} /></div>
          </header>
          <div className="product-entity-nav">
            <strong>DDL Benchmark Engine<span className="product-status-dot" /></strong>
            <span>Оптимизация физического дизайна</span>
          </div>
          <div className="product-content">{children}</div>
        </main>
      </div>
    </ThemeProvider>
  );
}
