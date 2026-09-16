/** Правая панель: сводка, проблемы и JSON. */

import { useState } from 'react';

import { CHECK_LEVEL_LABEL, SECTION_TITLE } from '../lib/issues';
import type { CheckLevel, Issue } from '../lib/issues';
import { copyToClipboard } from '../lib/download';
import { summaryRows } from '../lib/summary';
import { useEditor } from '../state/editor';

const LOCAL_LEVELS: CheckLevel[] = ['json', 'structure', 'cross-file'];

function IssuesTab(): JSX.Element {
  const { issues, goToIssue, loadError, checkedAt, reference } = useEditor();

  const grouped = new Map<CheckLevel, Issue[]>();
  for (const issue of [...loadError, ...issues]) {
    const list = grouped.get(issue.check) ?? [];
    list.push(issue);
    grouped.set(issue.check, list);
  }

  return (
    <div>
      {checkedAt ? (
        <div className="notice notice-info">
          Проверка выполнена в {checkedAt}. Закрыты уровни 1–2
          {reference.connectionIds !== null || reference.ruleBankIds !== null
            ? ' и частично 3'
            : ''}
          .
        </div>
      ) : null}

      {LOCAL_LEVELS.map((level) => {
        const list = grouped.get(level) ?? [];
        return (
          <div className="level-group" key={level}>
            <h4>
              {CHECK_LEVEL_LABEL[level]}
              {list.length ? (
                <span className="badge badge-danger">{list.length}</span>
              ) : (
                <span className="badge badge-ok">чисто</span>
              )}
            </h4>
            {level === 'cross-file' && reference.connectionIds === null && reference.ruleBankIds === null ? (
              <div className="faint" style={{ marginBottom: 6 }}>
                Файлы подключений и банков правил не загружены — ссылки не проверялись.
              </div>
            ) : null}
            {list.map((issue, index) => (
              <button
                key={`${issue.path}-${issue.message}-${index}`}
                type="button"
                className={`issue-item ${issue.level}`}
                onClick={() => goToIssue(issue)}
              >
                <div>{issue.message}</div>
                <div className="issue-path">
                  {SECTION_TITLE[issue.section]} · {issue.path || 'корень файла'}
                </div>
              </button>
            ))}
          </div>
        );
      })}

      <div className="level-group">
        <h4>{CHECK_LEVEL_LABEL.engine}</h4>
        <div className="notice">
          Движок проверяет выражения scoring собственным валидатором. Здесь выполняется только
          локальная сверка имён и функций, полноценный запуск валидатора требует серверного вызова.
        </div>
      </div>

      <div className="level-group">
        <h4>{CHECK_LEVEL_LABEL.connection}</h4>
        <div className="notice">
          Существование баз, таблиц и колонок, корректность SQL и доступность подключения
          проверяются только обращением к ClickHouse. Без серверной интеграции это недоступно.
        </div>
      </div>
    </div>
  );
}

function JsonTab(): JSX.Element {
  const { documentJson, selectedJson, selected } = useEditor();
  const [scope, setScope] = useState<'benchmark' | 'file'>('benchmark');
  const [copied, setCopied] = useState(false);
  const text = scope === 'file' ? documentJson : selectedJson;

  return (
    <div className="stack-sm">
      <div className="row">
        <div className="segmented">
          <button
            type="button"
            className={scope === 'benchmark' ? 'active' : ''}
            onClick={() => setScope('benchmark')}
          >
            Бенчмарк
          </button>
          <button
            type="button"
            className={scope === 'file' ? 'active' : ''}
            onClick={() => setScope('file')}
          >
            Весь файл
          </button>
        </div>
        <button
          className="btn btn-sm"
          type="button"
          onClick={async () => {
            setCopied(await copyToClipboard(text));
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? 'Скопировано' : 'Копировать'}
        </button>
      </div>
      <div className="faint">
        {scope === 'benchmark' && selected
          ? `benchmarks[] → ${selected.id}`
          : 'Ровно то, что попадёт в экспортируемый файл.'}
      </div>
      <pre className="panel-json">{text}</pre>
    </div>
  );
}

function SummaryTab(): JSX.Element {
  const { selected, benchmarks, document: doc } = useEditor();
  if (!selected) return <div className="muted">Бенчмарк не выбран.</div>;

  return (
    <div className="stack">
      <dl className="summary-list">
        {summaryRows(selected).map((row) => (
          <div className="summary-row" key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <div className="divider" />
      <div className="faint">
        В файле {benchmarks.length} бенчмарк(ов){doc?.kind === 'project' ? ', формат project-конфига' : ''}.
      </div>
      <div className="notice">
        <strong>Что этот редактор не делает</strong>
        Не запускает бенчмарк, не читает каталог таблиц и не применяет DDL к исходной таблице.
        Для этого нужна отдельная серверная интеграция.
      </div>
    </div>
  );
}

export function SidePanel(): JSX.Element {
  const { panelTab, setPanelTab, issues, loadError } = useEditor();
  const errors = [...loadError, ...issues].filter((issue) => issue.level === 'error').length;

  return (
    <aside className="panel">
      <div className="panel-tabs">
        <button
          type="button"
          className={panelTab === 'summary' ? 'active' : ''}
          onClick={() => setPanelTab('summary')}
        >
          Сводка
        </button>
        <button
          type="button"
          className={panelTab === 'issues' ? 'active' : ''}
          onClick={() => setPanelTab('issues')}
        >
          Проверка
          {errors ? <span className="badge badge-danger">{errors}</span> : null}
        </button>
        <button
          type="button"
          className={panelTab === 'json' ? 'active' : ''}
          onClick={() => setPanelTab('json')}
        >
          JSON
        </button>
      </div>
      <div className="panel-body">
        {panelTab === 'summary' ? <SummaryTab /> : null}
        {panelTab === 'issues' ? <IssuesTab /> : null}
        {panelTab === 'json' ? <JsonTab /> : null}
      </div>
    </aside>
  );
}
