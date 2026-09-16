/** Состояние редактора конфигурации: один открытый файл и его бенчмарки. */

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import type { BenchmarkConfig } from '../types/config';
import { emptyBenchmark } from '../types/config';
import type { Issue, SectionId } from '../lib/issues';
import type { BenchmarksDocument } from '../lib/parse';
import { parseDocument } from '../lib/parse';
import { toJsonText, writeBenchmark, writeDocument } from '../lib/serialize';
import { collectExtraIssues, validateBenchmarks } from '../lib/validate';
import type { ReferenceData } from '../lib/validate';
import type { ConnectionSummary } from '../lib/reference';
import { parseReferenceFile } from '../lib/reference';
import { cloneNode, removeAt, replaceAt } from '../lib/edit';
import { SAMPLE_BENCHMARKS_JSON, SAMPLE_FILE_NAME } from '../lib/samples';

export type PanelTab = 'summary' | 'issues' | 'json';

interface ReferenceState extends ReferenceData {
  connections: ConnectionSummary[];
  connectionsFileName?: string;
  ruleBanksFileName?: string;
}

function snapshotById(benchmarks: BenchmarkConfig[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const benchmark of benchmarks) result[benchmark.id] = toJsonText(writeBenchmark(benchmark));
  return result;
}

const EMPTY_REFERENCE: ReferenceState = {
  connectionIds: null,
  ruleBankIds: null,
  connections: [],
};

export interface EditorApi {
  fileName: string | null;
  document: BenchmarksDocument | null;
  benchmarks: BenchmarkConfig[];
  selectedIndex: number;
  selected: BenchmarkConfig | null;
  section: SectionId;
  issues: Issue[];
  loadError: Issue[];
  dirty: boolean;
  checkedAt: string | null;
  reference: ReferenceState;
  panelOpen: boolean;
  panelTab: PanelTab;
  focusField: string | null;
  documentJson: string;
  selectedJson: string;

  openFile(fileName: string, text: string): void;
  loadSample(): void;
  createFile(): void;
  closeFile(): void;
  loadReference(fileName: string, text: string): string | null;
  clearReference(): void;

  selectBenchmark(index: number): void;
  setSection(section: SectionId): void;
  updateSelected(updater: (benchmark: BenchmarkConfig) => BenchmarkConfig): void;
  addBenchmark(): void;
  duplicateBenchmark(index: number): void;
  removeBenchmark(index: number): void;

  runCheck(): void;
  isBenchmarkDirty(benchmark: BenchmarkConfig): boolean;
  markExported(): void;
  setPanelOpen(open: boolean): void;
  setPanelTab(tab: PanelTab): void;
  goToIssue(issue: Issue): void;
  clearFocus(): void;
}

const EditorContext = createContext<EditorApi | null>(null);

export function useEditor(): EditorApi {
  const value = useContext(EditorContext);
  if (!value) throw new Error('useEditor вызван вне EditorProvider');
  return value;
}

export function EditorProvider({ children }: { children: ReactNode }): JSX.Element {
  const [fileName, setFileName] = useState<string | null>(null);
  const [document, setDocument] = useState<BenchmarksDocument | null>(null);
  const [baseline, setBaseline] = useState<string>('');
  const [baselineById, setBaselineById] = useState<Record<string, string>>({});
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [section, setSectionState] = useState<SectionId>('source');
  const [loadError, setLoadError] = useState<Issue[]>([]);
  const [reference, setReference] = useState<ReferenceState>(EMPTY_REFERENCE);
  const [panelOpen, setPanelOpen] = useState(true);
  const [panelTab, setPanelTab] = useState<PanelTab>('summary');
  const [focusField, setFocusField] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);

  const benchmarks = document?.benchmarks ?? [];
  const selected = benchmarks[selectedIndex] ?? null;

  const documentJson = useMemo(
    () => (document ? toJsonText(writeDocument(document)) : ''),
    [document],
  );
  const selectedJson = useMemo(
    () => (selected ? toJsonText(writeBenchmark(selected)) : ''),
    [selected],
  );

  const issues = useMemo(() => {
    if (!document) return [];
    return [
      ...validateBenchmarks(document.benchmarks, reference),
      ...collectExtraIssues(document.benchmarks),
    ];
  }, [document, reference]);

  const dirty = Boolean(document) && documentJson !== baseline;

  const applyDocument = useCallback(
    (next: BenchmarksDocument, name: string, issuesFromParse: Issue[]) => {
      setDocument(next);
      setFileName(name);
      setBaseline(toJsonText(writeDocument(next)));
      setBaselineById(snapshotById(next.benchmarks));
      setSelectedIndex(0);
      setSectionState('source');
      setLoadError(issuesFromParse.filter((issue) => issue.check === 'json'));
      setCheckedAt(null);
    },
    [],
  );

  const openFile = useCallback(
    (name: string, text: string) => {
      const outcome = parseDocument(text);
      if (!outcome.document) {
        setLoadError(outcome.issues);
        return;
      }
      applyDocument(outcome.document, name, outcome.issues);
    },
    [applyDocument],
  );

  const loadSample = useCallback(() => {
    openFile(SAMPLE_FILE_NAME, SAMPLE_BENCHMARKS_JSON);
  }, [openFile]);

  const createFile = useCallback(() => {
    const next: BenchmarksDocument = {
      kind: 'benchmarks',
      benchmarks: [emptyBenchmark('new_benchmark')],
    };
    applyDocument(next, 'benchmarks.new.json', []);
  }, [applyDocument]);

  const closeFile = useCallback(() => {
    setDocument(null);
    setFileName(null);
    setBaseline('');
    setLoadError([]);
    setCheckedAt(null);
  }, []);

  const loadReference = useCallback((name: string, text: string): string | null => {
    const result = parseReferenceFile(text);
    if (result.error) return result.error;
    if (result.kind === 'connections' && result.connections) {
      setReference((prev) => ({
        ...prev,
        connections: result.connections ?? [],
        connectionIds: (result.connections ?? []).map((item) => item.id),
        connectionsFileName: name,
      }));
      return null;
    }
    if (result.kind === 'rule_banks') {
      setReference((prev) => ({
        ...prev,
        ruleBankIds: result.ruleBanks ?? [],
        ruleBanksFileName: name,
      }));
      return null;
    }
    return 'Файл не распознан';
  }, []);

  const clearReference = useCallback(() => setReference(EMPTY_REFERENCE), []);

  const updateSelected = useCallback(
    (updater: (benchmark: BenchmarkConfig) => BenchmarkConfig) => {
      setDocument((prev) => {
        if (!prev) return prev;
        const current = prev.benchmarks[selectedIndex];
        if (!current) return prev;
        return { ...prev, benchmarks: replaceAt(prev.benchmarks, selectedIndex, updater(current)) };
      });
    },
    [selectedIndex],
  );

  const addBenchmark = useCallback(() => {
    setDocument((prev) => {
      if (!prev) return prev;
      const base = `benchmark_${prev.benchmarks.length + 1}`;
      const next = [...prev.benchmarks, emptyBenchmark(base)];
      setSelectedIndex(next.length - 1);
      setSectionState('source');
      return { ...prev, benchmarks: next };
    });
  }, []);

  const duplicateBenchmark = useCallback((index: number) => {
    setDocument((prev) => {
      if (!prev) return prev;
      const source = prev.benchmarks[index];
      if (!source) return prev;
      const copy = cloneNode(source);
      copy.id = `${source.id}_copy`;
      copy.$seen = [...(copy.$seen ?? []), 'id'];
      const next = [...prev.benchmarks];
      next.splice(index + 1, 0, copy);
      setSelectedIndex(index + 1);
      return { ...prev, benchmarks: next };
    });
  }, []);

  const removeBenchmark = useCallback((index: number) => {
    setDocument((prev) => {
      if (!prev) return prev;
      const next = removeAt(prev.benchmarks, index);
      setSelectedIndex((current) => Math.max(0, Math.min(current, next.length - 1)));
      return { ...prev, benchmarks: next };
    });
  }, []);

  const runCheck = useCallback(() => {
    setCheckedAt(new Date().toLocaleTimeString('ru-RU'));
    setPanelOpen(true);
    setPanelTab('issues');
  }, []);

  const markExported = useCallback(() => {
    setBaseline(documentJson);
    if (document) setBaselineById(snapshotById(document.benchmarks));
  }, [document, documentJson]);

  const isBenchmarkDirty = useCallback(
    (benchmark: BenchmarkConfig): boolean => {
      const saved = baselineById[benchmark.id];
      if (saved === undefined) return true;
      return saved !== toJsonText(writeBenchmark(benchmark));
    },
    [baselineById],
  );

  const goToIssue = useCallback(
    (issue: Issue) => {
      if (issue.benchmarkId) {
        const index = benchmarks.findIndex((item) => item.id === issue.benchmarkId);
        if (index >= 0) setSelectedIndex(index);
      }
      setSectionState(issue.section);
      setFocusField(issue.field ?? null);
    },
    [benchmarks],
  );

  const api: EditorApi = {
    fileName,
    document,
    benchmarks,
    selectedIndex,
    selected,
    section,
    issues,
    loadError,
    dirty,
    checkedAt,
    reference,
    panelOpen,
    panelTab,
    focusField,
    documentJson,
    selectedJson,
    openFile,
    loadSample,
    createFile,
    closeFile,
    loadReference,
    clearReference,
    selectBenchmark: setSelectedIndex,
    setSection: setSectionState,
    updateSelected,
    addBenchmark,
    duplicateBenchmark,
    removeBenchmark,
    runCheck,
    isBenchmarkDirty,
    markExported,
    setPanelOpen,
    setPanelTab,
    goToIssue,
    clearFocus: () => setFocusField(null),
  };

  return <EditorContext.Provider value={api}>{children}</EditorContext.Provider>;
}
