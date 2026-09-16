/** Каркас приложения: список бенчмарков, редактор разделов и правая панель. */

import { SECTION_TAB_LABEL, SECTION_TITLE } from './lib/issues';
import type { SectionId } from './lib/issues';
import { EmptyState } from './components/EmptyState';
import { Sidebar } from './components/Sidebar';
import { SidePanel } from './components/SidePanel';
import { TopBar } from './components/TopBar';
import { IssueScopeProvider } from './components/fields/Field';
import { LimitsSection } from './components/sections/LimitsSection';
import { QueriesSection } from './components/sections/QueriesSection';
import { RulesSection } from './components/sections/RulesSection';
import { ScoringSection } from './components/sections/ScoringSection';
import { SourceSection } from './components/sections/SourceSection';
import { TableRulesSection } from './components/sections/TableRulesSection';
import { useEditor } from './state/editor';

const SECTIONS: SectionId[] = ['source', 'rules', 'queries', 'limits', 'scoring', 'tables'];

function Editor(): JSX.Element {
  const { selected, selectedIndex, section, setSection, issues } = useEditor();

  if (!selected) {
    return (
      <div className="editor">
        <div className="editor-scroll">
          <div className="notice">В файле нет ни одного бенчмарка.</div>
        </div>
      </div>
    );
  }

  const own = issues.filter((issue) => issue.benchmarkId === selected.id);

  return (
    <IssueScopeProvider prefix={`benchmarks[${selectedIndex}]`} issues={own}>
      <div className="editor">
        <nav className="section-tabs">
          {SECTIONS.map((id) => {
            const errors = own.filter(
              (issue) => issue.section === id && issue.level === 'error',
            ).length;
            return (
              <button
                key={id}
                type="button"
                className={`section-tab${section === id ? ' active' : ''}`}
                onClick={() => setSection(id)}
              >
                <span title={SECTION_TITLE[id]}>{SECTION_TAB_LABEL[id]}</span>
                {errors ? <span className="badge badge-danger">{errors}</span> : null}
              </button>
            );
          })}
        </nav>

        <div className="editor-scroll">
          <div className="editor-inner">
            {section === 'source' ? <SourceSection benchmark={selected} /> : null}
            {section === 'rules' ? <RulesSection benchmark={selected} /> : null}
            {section === 'queries' ? <QueriesSection benchmark={selected} /> : null}
            {section === 'limits' ? <LimitsSection benchmark={selected} /> : null}
            {section === 'scoring' ? <ScoringSection benchmark={selected} /> : null}
            {section === 'tables' ? <TableRulesSection benchmark={selected} /> : null}
          </div>
        </div>
      </div>
    </IssueScopeProvider>
  );
}

export function App(): JSX.Element {
  const { document: doc, panelOpen } = useEditor();

  return (
    <div className="app">
      <TopBar />
      {doc ? (
        <div className={`app-body${panelOpen ? ' with-panel' : ''}`}>
          <Sidebar />
          <Editor />
          {panelOpen ? <SidePanel /> : null}
        </div>
      ) : (
        <EmptyState />
      )}
    </div>
  );
}
