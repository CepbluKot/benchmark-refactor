/** Раздел «Оценка кандидатов». */

import type { BenchmarkConfig } from '../../types/config';
import { patch } from '../../lib/edit';
import { SCORING_ROOT_NAMES } from '../../lib/vocab';
import { useEditor } from '../../state/editor';
import { ScoringEditor } from '../scoring/ScoringEditor';
import { Card, Disclosure } from '../fields/inputs';

export function ScoringSection({ benchmark }: { benchmark: BenchmarkConfig }): JSX.Element {
  const { updateSelected } = useEditor();

  return (
    <>
      <div className="section-head">
        <h2>Оценка</h2>
        <p>
          По какой формуле сравниваются кандидаты. Смысл переменной задаётся её выражением:
          например, <code>select_ratio</code> в конфигурациях проекта — отношение объёмов
          прочитанных данных, а не ускорение запроса.
        </p>
      </div>

      <Card title="Формула оценки" subtitle="scoring">
        <ScoringEditor
          scoring={benchmark.scoring}
          path="scoring"
          onChange={(next) =>
            updateSelected((current) => patch(current, { scoring: next } as Partial<BenchmarkConfig>))
          }
        />
      </Card>

      <Disclosure title="Корневые имена метрик, доступные в выражениях">
        <div className="faint" style={{ marginBottom: 8 }}>
          Список whitelist движка. Обращение к вложенным полям записывается через точку,
          например <code>medians.source_select_read_bytes</code>.
        </div>
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {SCORING_ROOT_NAMES.map((name) => (
                <tr key={name}>
                  <td className="mono">{name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Disclosure>
    </>
  );
}
