import { SECTION_TAB_LABEL, SECTION_TITLE } from '../lib/issues';
import type { SectionId } from '../lib/issues';
import { Button, Tabs } from '@adqm/gpb-ui';
import { Sidebar } from './Sidebar';
import { SidePanel } from './SidePanel';
import { TopBar } from './TopBar';
import { IssueScopeProvider } from './fields/Field';
import { LimitsSection } from './sections/LimitsSection';
import { QueriesSection } from './sections/QueriesSection';
import { RulesSection } from './sections/RulesSection';
import { ScoringSection } from './sections/ScoringSection';
import { SourceSection } from './sections/SourceSection';
import { TableRulesSection } from './sections/TableRulesSection';
import { useEditor } from '../state/editor';

const SECTIONS: SectionId[] = ['source', 'rules', 'queries', 'limits', 'scoring', 'tables'];

function Editor(): JSX.Element {
  const { selected, selectedIndex, section, setSection, issues } = useEditor();
  if (!selected) return <div className="notice">В файле нет ни одного бенчмарка.</div>;
  const own = issues.filter((issue) => issue.benchmarkId === selected.id);

  return (
    <IssueScopeProvider prefix={`benchmarks[${selectedIndex}]`} issues={own}>
      <div className="editor">
        <Tabs
          label="Разделы конфигурации бенчмарка"
          variant="secondary"
          value={section}
          onValueChange={(next) => setSection(next as SectionId)}
          items={SECTIONS.map((id) => {
            const errors = own.filter((issue) => issue.section === id && issue.level === 'error').length;
            return { value: id, label: <span title={SECTION_TITLE[id]}>{SECTION_TAB_LABEL[id]}{errors ? <span className="badge badge-danger">{errors}</span> : null}</span> };
          })}
        />
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

export function BenchmarkEditor({ onBack }: { onBack(): void }): JSX.Element {
  const { panelOpen } = useEditor();
  return (
    <div className="benchmark-editor-shell">
      <div className="subpage-backbar">
        <Button variant="tertiary" onClick={onBack}>← К списку бенчмарков</Button>
      </div>
      <TopBar />
      <div className={`app-body${panelOpen ? ' with-panel' : ''}`}>
        <Sidebar />
        <Editor />
        {panelOpen ? <SidePanel /> : null}
      </div>
    </div>
  );
}
