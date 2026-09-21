import { MaterialIcon, type MaterialIconName } from './MaterialIcon';

export function WorkspaceIcon({ icon = 'target' }: { icon?: string }): JSX.Element {
  const name = ({ target: 'target', analytics: 'analytics', data: 'data', experiment: 'experiment', operations: 'operations' } as Record<string, MaterialIconName>)[icon] ?? 'target';
  return <MaterialIcon name={name} />;
}
