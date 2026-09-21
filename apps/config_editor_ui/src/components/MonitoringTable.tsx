import type { ReactNode } from 'react';
import { Button, DataTable } from '@adqm/gpb-ui';

export interface MonitoringTableColumn<Row> {
  key: string;
  label: string;
  render(row: Row): ReactNode;
  className?: string;
}

interface MonitoringTableProps<Row> {
  rows: Row[];
  columns: MonitoringTableColumn<Row>[];
  rowKey(row: Row): string;
  title: string;
  description: string;
  searchText(row: Row): string;
  searchPlaceholder?: string;
  filters?: ReactNode;
  emptyTitle?: string;
  emptyDescription?: string;
  pageSize?: number;
  compact?: boolean;
  filtersActive?: boolean;
  onResetFilters?: () => void;
}

/**
 * Product metadata and filters surround the unmodified ADQM DataTable.
 * Search, sorting and pagination remain implementation details of the design
 * system, so the product does not maintain a parallel table control.
 */
export function MonitoringTable<Row>({
  rows,
  columns,
  rowKey,
  title,
  description,
  searchText,
  searchPlaceholder,
  filters,
  pageSize = 5,
  filtersActive = false,
  onResetFilters,
}: MonitoringTableProps<Row>): JSX.Element {
  return (
    <div className="monitor-table-block">
      <section className="monitor-table-shell">
        <header className="monitor-table-heading">
          <div><h2>{title}</h2><p>{description}</p></div>
        </header>
        <DataTable
          rows={rows}
          columns={columns.map(({ key, label, render }) => ({ key, label, render }))}
          rowKey={rowKey}
          searchText={searchText}
          label={`Поиск в таблице «${title}»`}
          pageSize={pageSize}
          searchPlaceholder={searchPlaceholder}
          filters={filters ? <div className={`monitor-filter-set${filtersActive ? ' is-active' : ''}`}>{filters}{filtersActive ? <Button variant="tertiary" onClick={onResetFilters}>Сбросить</Button> : null}</div> : undefined}
        />
      </section>
    </div>
  );
}
