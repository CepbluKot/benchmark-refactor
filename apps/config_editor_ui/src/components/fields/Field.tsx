/** Базовые элементы формы: подпись, техническое имя, ошибки, фокус по проблеме. */

import { createContext, useContext, useEffect, useMemo, useRef } from 'react';
import type { ReactNode } from 'react';

import type { Issue } from '../../lib/issues';
import { useEditor } from '../../state/editor';

interface IssueScope {
  /** Префикс пути текущего бенчмарка, например `benchmarks[0]`. */
  prefix: string;
  issues: Issue[];
}

const IssueContext = createContext<IssueScope>({ prefix: '', issues: [] });

export function IssueScopeProvider({
  prefix,
  issues,
  children,
}: {
  prefix: string;
  issues: Issue[];
  children: ReactNode;
}): JSX.Element {
  const value = useMemo(() => ({ prefix, issues }), [prefix, issues]);
  return <IssueContext.Provider value={value}>{children}</IssueContext.Provider>;
}

/** Проблемы для конкретного пути: точное совпадение и вложенные пути. */
export function useIssuesFor(path: string | undefined): Issue[] {
  const scope = useContext(IssueContext);
  return useMemo(() => {
    if (!path) return [];
    const full = scope.prefix ? `${scope.prefix}.${path}` : path;
    return scope.issues.filter(
      (issue) =>
        issue.path === full || issue.path.startsWith(`${full}.`) || issue.path.startsWith(`${full}[`),
    );
  }, [path, scope]);
}

export interface FieldProps {
  label: string;
  /** Техническое имя поля в JSON. */
  jsonKey?: string;
  hint?: ReactNode;
  /** Путь для поиска проблем, относительный к текущему бенчмарку. */
  path?: string;
  /** Ключ для передачи фокуса по клику на проблему. */
  focusKey?: string;
  right?: ReactNode;
  children: ReactNode;
}

export function Field({
  label,
  jsonKey,
  hint,
  path,
  focusKey,
  right,
  children,
}: FieldProps): JSX.Element {
  const issues = useIssuesFor(path);
  const errors = issues.filter((issue) => issue.level === 'error');
  const warnings = issues.filter((issue) => issue.level === 'warning');
  const { focusField, clearFocus } = useEditor();
  const ref = useRef<HTMLDivElement>(null);
  const key = focusKey ?? jsonKey;
  const focused = Boolean(key) && focusField === key;

  useEffect(() => {
    if (!focused || !ref.current) return;
    ref.current.scrollIntoView({ block: 'center' });
    const control = ref.current.querySelector<HTMLElement>('input, select, textarea');
    control?.focus();
    const timer = window.setTimeout(clearFocus, 1200);
    return () => window.clearTimeout(timer);
  }, [focused, clearFocus]);

  return (
    <div className={`field${focused ? ' focused' : ''}`} ref={ref}>
      <div className="field-label">
        <span>{label}</span>
        {jsonKey ? <span className="field-key">{jsonKey}</span> : null}
        {right ? <span style={{ marginLeft: 'auto' }}>{right}</span> : null}
      </div>
      {children}
      {hint ? <div className="field-hint">{hint}</div> : null}
      {errors.map((issue) => (
        <div className="field-error" key={`${issue.path}-${issue.message}`}>
          {issue.message}
        </div>
      ))}
      {warnings.map((issue) => (
        <div className="field-warn" key={`${issue.path}-${issue.message}`}>
          {issue.message}
        </div>
      ))}
    </div>
  );
}

export function hasError(issues: Issue[]): boolean {
  return issues.some((issue) => issue.level === 'error');
}
