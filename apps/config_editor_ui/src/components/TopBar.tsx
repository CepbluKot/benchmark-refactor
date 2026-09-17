/** Верхняя панель: файл, выбранный бенчмарк, состояние и основные действия. */

import { useRef, useState } from 'react';
import { Button, Modal, TextArea } from '@adqm/gpb-ui';

import { downloadText } from '../lib/download';
import { useEditor } from '../state/editor';

function ImportDialog({ onClose }: { onClose(): void }): JSX.Element {
  const { openFile } = useEditor();
  const [text, setText] = useState('');

  return (
    <Modal open onClose={onClose} title="Вставить JSON конфигурации" footer={<><Button variant="secondary" onClick={onClose}>Отмена</Button><Button variant="primary" disabled={!text.trim()} onClick={() => { openFile('benchmarks.pasted.json', text); onClose(); }}>Открыть</Button></>}>
      <p className="field-help">Ожидается файл со списком `benchmarks`.</p>
      <TextArea label="Конфигурация" spellCheck={false} rows={12} value={text} placeholder='{ "benchmarks": [ ... ] }' onChange={(event) => setText(event.target.value)} />
    </Modal>
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

        <Button variant="secondary" onClick={() => fileInput.current?.click()}>Импорт JSON</Button>
        <Button variant="tertiary" onClick={() => setPaste(true)}>Вставить JSON</Button>
        <Button
          variant="tertiary"
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
        </Button>
        <Button variant="secondary" disabled={!doc} onClick={runCheck}>Проверить</Button>
        <Button
          variant="primary"
          disabled={!doc}
          onClick={() => {
            downloadText(fileName ?? 'benchmarks.json', documentJson);
            markExported();
          }}
        >
          Экспорт JSON
        </Button>
        <Button
          variant="tertiary"
          onClick={() => setPanelOpen(!panelOpen)}
          title={panelOpen ? 'Свернуть правую панель' : 'Развернуть правую панель'}
        >
          {panelOpen ? '⟩' : '⟨'}
        </Button>
      </div>

      {paste ? <ImportDialog onClose={() => setPaste(false)} /> : null}
      {referenceError ? <Modal open onClose={() => setReferenceError(null)} title="Справочный файл не загружен" footer={<Button variant="primary" onClick={() => setReferenceError(null)}>Закрыть</Button>}>{referenceError}</Modal> : null}
    </header>
  );
}
