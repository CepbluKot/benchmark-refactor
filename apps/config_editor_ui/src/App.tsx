import { useEffect, useState } from 'react';
import { ComponentGallery } from '@adqm/gpb-ui';

import { ProductShell } from './components/ProductShell';
import type { ProductPage } from './components/ProductShell';
import { useWorkspace } from './demo/workspace';
import { BenchmarksPage } from './pages/BenchmarksPage';
import { RuleBanksPage } from './pages/RuleBanksPage';
import { RunsPage } from './pages/RunsPage';
import { SourcesPage } from './pages/SourcesPage';
import { useEditor } from './state/editor';

export function App(): JSX.Element {
  if (window.location.pathname === '/design-system') {
    return <ComponentGallery backHref="/" backLabel="К DDL Benchmark Engine" />;
  }

  const editor = useEditor();
  const { sources, ruleBanks } = useWorkspace();
  const [page, setPage] = useState<ProductPage>('benchmarks');
  const [editingBenchmark, setEditingBenchmark] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  useEffect(() => {
    if (!editor.document) editor.loadSample();
  }, [editor.document, editor.loadSample]);

  useEffect(() => {
    editor.loadReference('connections.demo.json', JSON.stringify({ connections: sources }));
  }, [editor.loadReference, sources]);

  useEffect(() => {
    editor.loadReference('rule_banks.demo.json', JSON.stringify({
      rule_banks: Object.fromEntries(ruleBanks.map((bank) => [bank.id, {}])),
    }));
  }, [editor.loadReference, ruleBanks]);

  const openRun = (id: string) => {
    setSelectedRunId(id);
    setPage('runs');
  };

  return (
    <ProductShell page={page} onPageChange={(next) => {
      setPage(next);
      setEditingBenchmark(false);
      if (next === 'runs') setSelectedRunId(null);
    }}>
      {page === 'sources' ? <SourcesPage /> : null}
      {page === 'benchmarks' ? <BenchmarksPage editing={editingBenchmark} onEditingChange={setEditingBenchmark} onOpenRun={openRun} /> : null}
      {page === 'runs' ? <RunsPage selectedId={selectedRunId} onSelectedId={setSelectedRunId} /> : null}
      {page === 'rule-banks' ? <RuleBanksPage /> : null}
    </ProductShell>
  );
}
