/** Экран «файл ещё не открыт» и сообщения о неудачном импорте. */

import { useRef } from 'react';
import { Alert, Button, EmptyState as AdqmEmptyState } from '@adqm/gpb-ui';

import { SAMPLE_FILE_PATH } from '../lib/samples';
import { useEditor } from '../state/editor';

export function EmptyState(): JSX.Element {
  const { openFile, loadSample, createFile, loadError } = useEditor();
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className="empty-state">
      <div className="empty-card">
        <AdqmEmptyState title="Файл конфигурации не открыт" description="Редактор работает с JSON, содержащим непустой список benchmarks." />

        {loadError.length ? (
          <Alert tone="danger" title="Файл не открыт">{loadError.map((issue) => <div key={issue.message}>{issue.message}</div>)}</Alert>
        ) : null}

        <input
          ref={input}
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

        <div className="empty-actions">
          <Button variant="primary" onClick={() => input.current?.click()}>Открыть файл</Button>
          <Button variant="secondary" onClick={loadSample}>Загрузить пример проекта</Button>
          <Button variant="secondary" onClick={createFile}>Создать пустой файл</Button>
        </div>

        <div className="faint" style={{ marginBottom: 14 }}>
          Пример соответствует файлу <code>{SAMPLE_FILE_PATH}</code> и дополнен вторым
          бенчмарком со стратегией <code>types_strategy</code>.
        </div>

        <div className="divider" />

        <h3 style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-faint)', marginBottom: 6 }}>
          Порядок работы
        </h3>
        <ol className="steps">
          <li>Открыть файл конфигурации и выбрать бенчмарк.</li>
          <li>Указать подключение, базы и таблицы источника.</li>
          <li>Выбрать стратегию перебора.</li>
          <li>Настроить правила генерации вариантов.</li>
          <li>Задать тестовые SQL-запросы.</li>
          <li>Ограничить перебор и настроить формулу оценки.</li>
          <li>При необходимости добавить переопределения для отдельных таблиц.</li>
          <li>Проверить конфигурацию и выгрузить JSON.</li>
        </ol>
      </div>
    </div>
  );
}
