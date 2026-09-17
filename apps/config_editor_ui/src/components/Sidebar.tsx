/** Список бенчмарков текущего файла. */

import { Button } from '@adqm/gpb-ui';

import { describeTarget } from '../lib/summary';
import { strategyLabel } from '../lib/vocab';
import { useEditor } from '../state/editor';

export function Sidebar(): JSX.Element {
  const {
    benchmarks,
    selectedIndex,
    selectBenchmark,
    issues,
    addBenchmark,
    duplicateBenchmark,
    removeBenchmark,
    isBenchmarkDirty,
  } = useEditor();

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <h2>Бенчмарки файла</h2>
        <span className="badge badge-neutral">{benchmarks.length}</span>
      </div>

      <div className="sidebar-list">
        {benchmarks.map((benchmark, index) => {
          const own = issues.filter((issue) => issue.benchmarkId === benchmark.id);
          const errors = own.filter((issue) => issue.level === 'error').length;
          const warnings = own.filter((issue) => issue.level === 'warning').length;
          const dirty = isBenchmarkDirty(benchmark);
          return (
            <button
              key={`${benchmark.id}-${index}`}
              type="button"
              className={`bench-item${index === selectedIndex ? ' active' : ''}`}
              onClick={() => selectBenchmark(index)}
            >
              <div className="bench-item-id">
                {errors ? (
                  <span className="dot dot-danger" title={`ошибок: ${errors}`} />
                ) : warnings ? (
                  <span className="dot dot-warn" title={`замечаний: ${warnings}`} />
                ) : null}
                {dirty ? <span className="dot dot-dirty" title="есть несохранённые изменения" /> : null}
                <span>{benchmark.id || '(без id)'}</span>
              </div>
              <div className="bench-item-meta">{strategyLabel(benchmark.strategy)}</div>
              <div className="bench-item-target">{describeTarget(benchmark)}</div>
            </button>
          );
        })}
      </div>

      <div className="sidebar-foot">
        <div className="inline-actions">
          <Button variant="secondary" onClick={addBenchmark}>Добавить</Button>
          <Button
            variant="secondary"
            disabled={!benchmarks.length}
            onClick={() => duplicateBenchmark(selectedIndex)}
          >
            Дублировать
          </Button>
          <Button
            variant="danger"
            disabled={benchmarks.length <= 1}
            onClick={() => removeBenchmark(selectedIndex)}
          >
            Удалить
          </Button>
        </div>
        <div className="faint">
          Точка слева: красная — ошибки, синяя — несохранённые изменения.
        </div>
      </div>
    </aside>
  );
}
