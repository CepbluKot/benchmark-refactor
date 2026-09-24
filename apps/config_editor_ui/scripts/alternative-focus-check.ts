import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const source = readFileSync(join(process.cwd(), 'src', 'components', 'AlternativeChipInput.tsx'), 'utf8');
const sourceType = readFileSync(join(process.cwd(), 'src', 'components', 'SourceTypeAutocomplete.tsx'), 'utf8');
if (!source.includes("onChange([...values, normalized]);\n    setQuery(''); setOpen(showSuggestions);")) {
  throw new Error('Adding an alternative must reopen suggestions when the input keeps focus');
}
if (!source.includes('className="alternative-picker" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>')) {
  throw new Error('Alternative suggestions must close when focus leaves the picker');
}
if (!sourceType.includes('className="source-type-autocomplete" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>')) {
  throw new Error('Source-type suggestions must close when focus leaves the picker');
}
console.log('Alternative picker focus checks passed');
