import { MaterialIcon, type MaterialIconName } from './MaterialIcon';

export type ActionIconName = 'configure' | 'start' | 'check' | 'edit' | 'delete';

export function ActionIcon({ name }: { name: ActionIconName }): JSX.Element {
  const materialName: Record<ActionIconName, MaterialIconName> = { configure: 'tune', start: 'play', check: 'settings', edit: 'edit', delete: 'delete' };
  return <MaterialIcon name={materialName[name]} />;
}
