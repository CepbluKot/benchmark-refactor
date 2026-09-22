import { useState } from 'react';
import { Alert } from '@adqm/gpb-ui';
import { ProductShell } from './components/ProductShell';
import type { ProductPage } from './components/ProductShell';
import { useWorkspace } from './control/workspace';
import { BenchmarksPage } from './pages/BenchmarksPage';
import { CreateBenchmarkPage } from './pages/CreateBenchmarkPage';
import { DesignSystemPage } from './pages/DesignSystemPage';
import { EditBenchmarkPage } from './pages/EditBenchmarkPage';
import { RuleBanksPage } from './pages/RuleBanksPage';
import { RunsPage } from './pages/RunsPage';
import { SourcesPage } from './pages/SourcesPage';
import { StrategyEditorPage } from './pages/StrategyEditorPage';
import { useI18n } from './i18n';
import { PRODUCT_PAGE_STORAGE_KEY, productPageFromUrl, restoreProductPage, savedProductPage } from './navigation-state';

function initialProductPage(): ProductPage {
  if (window.location.pathname === '/design-system') return 'design-system';
  const urlPage = productPageFromUrl(window.location.href);
  if (urlPage !== 'benchmarks') return urlPage;
  try { return restoreProductPage(window.localStorage.getItem(PRODUCT_PAGE_STORAGE_KEY)); } catch { return 'benchmarks'; }
}

export function App(): JSX.Element { const { ready, error } = useWorkspace(); const { t } = useI18n(); const [page, setPage] = useState<ProductPage>(initialProductPage); const [selectedRunId, setSelectedRunId] = useState<string | null>(null); const [editingBenchmarkId, setEditingBenchmarkId] = useState<string | null>(null); const [editingStrategyId, setEditingStrategyId] = useState<string | null>(null); if (!ready) return <main className="app-loading"><h1>DB Benchmark</h1>{error ? <Alert tone="danger" title={t('Нет связи с Control API', 'Control API is unavailable')}>{error}</Alert> : <p>{t('Загружаем состояние бенчмарков…', 'Loading benchmark state…')}</p>}</main>; const changePage = (next: ProductPage) => { const savedPage = savedProductPage(next); try { window.localStorage.setItem(PRODUCT_PAGE_STORAGE_KEY, savedPage); } catch { /* Browser storage is optional for navigation memory. */ } try { const url = new URL(window.location.href); if (savedPage === 'benchmarks') url.searchParams.delete('page'); else url.searchParams.set('page', savedPage); window.history.replaceState(null, '', url); } catch { /* The current address remains usable if history is unavailable. */ } setPage(next); if (next === 'runs') setSelectedRunId(null); }; return <ProductShell page={page} onPageChange={changePage}>{error ? <Alert tone="warning" title={t('Обновления в реальном времени отключены', 'Real-time updates are unavailable')}>{error}</Alert> : null}{page === 'sources' ? <SourcesPage /> : null}{page === 'benchmarks' ? <BenchmarksPage onCreate={() => setPage('create-benchmark')} onEdit={(id) => { setEditingBenchmarkId(id); setPage('edit-benchmark'); }} /> : null}{page === 'create-benchmark' ? <CreateBenchmarkPage onCancel={() => setPage('benchmarks')} onDone={() => setPage('benchmarks')} /> : null}{page === 'edit-benchmark' && editingBenchmarkId ? <EditBenchmarkPage benchmarkId={editingBenchmarkId} onCancel={() => setPage('benchmarks')} onDone={() => setPage('benchmarks')} /> : null}{page === 'runs' ? <RunsPage selectedId={selectedRunId} onSelectedId={setSelectedRunId} /> : null}{page === 'strategies' ? <RuleBanksPage onCreate={() => setPage('create-strategy')} onEdit={(id) => { setEditingStrategyId(id); setPage('edit-strategy'); }} /> : null}{page === 'create-strategy' ? <StrategyEditorPage onCancel={() => setPage('strategies')} onDone={() => setPage('strategies')} /> : null}{page === 'edit-strategy' && editingStrategyId ? <StrategyEditorPage strategyId={editingStrategyId} onCancel={() => setPage('strategies')} onDone={() => setPage('strategies')} /> : null}{page === 'design-system' ? <DesignSystemPage /> : null}</ProductShell>; }
