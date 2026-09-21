/**
 * DB Benchmark - Enterprise Web Application
 * ClickHouse Table Physical Structure Optimization & Experimentation
 */

import React from 'react';
import { BenchmarkProvider, useBenchmark } from './context/BenchmarkContext';
import { Shell } from './components/layout/Shell';
import { BenchmarksListView } from './views/BenchmarksListView';
import { BenchmarkCreateWizardView } from './views/BenchmarkCreateWizardView';
import { BenchmarkEditView } from './views/BenchmarkEditView';
import { DataSourcesView } from './views/DataSourcesView';
import { StrategiesView } from './views/StrategiesView';
import { RunsListView } from './views/RunsListView';
import { RunDetailView } from './views/RunDetailView';
import { DesignSystemCatalogView } from './views/DesignSystemCatalogView';

const AppContent: React.FC = () => {
  const { currentTab } = useBenchmark();

  return (
    <Shell>
      {currentTab === 'benchmarks' && <BenchmarksListView />}
      {currentTab === 'benchmark-create' && <BenchmarkCreateWizardView />}
      {currentTab === 'benchmark-edit' && <BenchmarkEditView />}
      {currentTab === 'data-sources' && <DataSourcesView />}
      {currentTab === 'strategies' && <StrategiesView />}
      {currentTab === 'runs' && <RunsListView />}
      {currentTab === 'run-detail' && <RunDetailView />}
      {currentTab === 'design-system' && <DesignSystemCatalogView />}
    </Shell>
  );
};

export default function App() {
  return (
    <BenchmarkProvider>
      <AppContent />
    </BenchmarkProvider>
  );
}
