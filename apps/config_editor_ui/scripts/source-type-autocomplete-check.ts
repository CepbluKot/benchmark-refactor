import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const component = join(process.cwd(), 'src', 'components', 'SourceTypeAutocomplete.tsx');
if (!existsSync(component)) throw new Error('Source column type autocomplete component is missing');

const source = readFileSync(component, 'utf8');
for (const expected of ["kind=\"source_type\"", 'role="combobox"', 'aria-autocomplete="list"', 'onSelect']) {
  if (!source.includes(expected)) throw new Error(`Source type autocomplete is missing ${expected}`);
}

const editor = readFileSync(join(process.cwd(), 'src', 'components', 'StrategyDimensionsEditor.tsx'), 'utf8');
if (!editor.includes('<SourceTypeAutocomplete')) throw new Error('Strategy rule editors do not use source type autocomplete');
console.log('Source type autocomplete checks passed');
