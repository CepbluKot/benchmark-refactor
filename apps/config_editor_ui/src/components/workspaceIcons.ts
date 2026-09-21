export const WORKSPACE_ICON_OPTIONS = [
  { value: 'target', label: 'Контур' },
  { value: 'analytics', label: 'Аналитика' },
  { value: 'data', label: 'Данные' },
  { value: 'experiment', label: 'Эксперимент' },
  { value: 'operations', label: 'Операции' },
] as const;

export type WorkspaceIcon = (typeof WORKSPACE_ICON_OPTIONS)[number]['value'];
