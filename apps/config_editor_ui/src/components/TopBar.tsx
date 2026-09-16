/** Верхняя панель: файл, выбранный бенчмарк, состояние и основные действия. */

import { useRef, useState } from 'react';

import { downloadText } from '../lib/download';
import { useEditor } from '../state/editor';

function ImportDialog({ onClose }: { onClose(): void }): JSX.Element {
  const { openFile } = useEditor();
  const [text, setText] = useState('');

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h3>Вставить JSON конфигурации</h3>
          <span className="faint" style={{ marginLeft: 'auto' }}>
            ожидается файл со списком benchmarks
          </span>
        </div>
        <div className="modal-body">
          <textarea
            spellCheck={false}
            value={text}
            placeholder='{ "benchmarks": [ ... ] }'
            onChange={(event) => setText(event.target.value)}
          />
        </div>
        <div className="modal-foot">
          <button className="btn" type="button" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!text.trim()}
            onClick={() => {
              openFile('benchmarks.pasted.json', text);
              onClose();
            }}
          >
            Открыть
          </button>
        </div>
      </div>
    </div>
  );
}

export function TopBar(): JSX.Element {
  const {
    fileName,
    document: doc,
    selected,
    dirty,
    issues,
    openFile,
    loadReference,
    reference,
    runCheck,
    markExported,
    documentJson,
    panelOpen,
    setPanelOpen,
  } = useEditor();

  const fileInput = useRef<HTMLInputElement>(null);
  const referenceInput = useRef<HTMLInputElement>(null);
  const [paste, setPaste] = useState(false);
  const [referenceError, setReferenceError] = useState<string | null>(null);

  const errors = issues.filter((issue) => issue.level === 'error').length;
  const warnings = issues.filter((issue) => issue.level === 'warning').length;

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <strong>DDL Benchmark Engine</strong>
        <span>редактор конфигурации</span>
      </div>

      <div className="topbar-file">
        {fileName ? (
          <>
            <span className="file-name" title={fileName}>
              {fileName}
            </span>
            {doc?.kind === 'project' ? (
              <span className="badge badge-neutral">project-конфиг</span>
            ) : null}
            {selected ? <span className="file-sub">бенчмарк: {selected.id}</span> : null}
            {dirty ? (
              <span className="badge badge-accent">
                <span className="dot dot-dirty" /> есть несохранённые изменения
              </span>
            ) : (
              <span className="badge badge-neutral">изменений нет</span>
            )}
          </>
        ) : (
          <span className="muted">файл не открыт</span>
        )}
      </div>

      <div className="topbar-actions">
        {fileName ? (
          <>
            {errors ? (
              <span className="badge badge-danger">
                <span className="dot dot-danger" /> ошибок: {errors}
              </span>
            ) : (
              <span className="badge badge-ok">ошибок нет</span>
            )}
            {warnings ? <span className="badge badge-warn">замечаний: {warnings}</span> : null}
          </>
        ) : null}

        <input
          ref={fileInput}
          className="file-input"
          type="file"
          accept="application/json,.json"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            openFile(file.name, await file.text());
            event.target.value = '';
          }}
        />
        <input
          ref={referenceInput}
          className="file-input"
          type="file"
          accept="application/json,.json"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            setReferenceError(loadReference(file.name, await file.text()));
            event.target.value = '';
          }}
        />

        <button className="btn" type="button" onClick={() => fileInput.current?.click()}>
          Импорт JSON
        </button>
        <button className="btn btn-ghost" type="button" onClick={() => setPaste(true)}>
          Вставить JSON
        </button>
        <button
          className="btn btn-ghost"
          type="button"
          title={
            reference.connectionIds === null && reference.ruleBankIds === null
              ? 'Загрузить connections.json или rule_banks.json, чтобы включить проверку ссылок'
              : `Загружено: ${[reference.connectionsFileName, reference.ruleBanksFileName]
                  .filter(Boolean)
                  .join(', ')}`
          }
          onClick={() => referenceInput.current?.click()}
        >
          Справочные файлы
          {reference.connectionIds !== null || reference.ruleBankIds !== null ? ' ✓' : ''}
        </button>
        <button className="btn" type="button" disabled={!doc} onClick={runCheck}>
          Проверить
        </button>
        <button
          className="btn btn-primary"
          type="button"
          disabled={!doc}
          onClick={() => {
            downloadText(fileName ?? 'benchmarks.json', documentJson);
            markExported();
          }}
        >
          Экспорт JSON
        </button>
        <button
          className="btn btn-ghost"
          type="button"
          onClick={() => setPanelOpen(!panelOpen)}
          title={panelOpen ? 'Свернуть правую панель' : 'Развернуть правую панель'}
        >
          {panelOpen ? '⟩' : '⟨'}
        </button>
      </div>

      {paste ? <ImportDialog onClose={() => setPaste(false)} /> : null}
      {referenceError ? (
        <div className="modal-backdrop" onClick={() => setReferenceError(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <h3>Справочный файл не загружен</h3>
            </div>
            <div className="modal-body">{referenceError}</div>
            <div className="modal-foot">
              <button className="btn" type="button" onClick={() => setReferenceError(null)}>
                Закрыть
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
