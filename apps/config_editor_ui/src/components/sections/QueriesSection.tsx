/** Раздел «Тестовые запросы». */

import type { BenchmarkConfig } from '../../types/config';
import { patch } from '../../lib/edit';
import { useEditor } from '../../state/editor';
import { QueriesEditor } from '../queries/QueriesEditor';
import { Card } from '../fields/inputs';

export function QueriesSection({ benchmark }: { benchmark: BenchmarkConfig }): JSX.Element {
  const { updateSelected } = useEditor();

  return (
    <>
      <div className="section-head">
        <h2>Тестовые запросы</h2>
        <p>
          SELECT-нагрузка, по которой сравниваются кандидаты. Планы выполнения, длительности
          и строки результата появятся только после реального запуска.
        </p>
      </div>

      <Card title="Запросы бенчмарка" subtitle="queries">
        <QueriesEditor
          queries={benchmark.queries}
          path="queries"
          onChange={(next) =>
            updateSelected((current) => patch(current, { queries: next } as Partial<BenchmarkConfig>))
          }
        />
      </Card>
    </>
  );
}
