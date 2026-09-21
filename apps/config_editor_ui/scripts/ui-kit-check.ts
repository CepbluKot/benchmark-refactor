import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const root = join(process.cwd(), 'src');
const productFiles = [
  ...readdirSync(join(root, 'pages')).filter((name) => name.endsWith('.tsx')).map((name) => join(root, 'pages', name)),
  join(root, 'components', 'ProductShell.tsx'),
];
const violations: string[] = [];
for (const file of productFiles) {
  const text = readFileSync(file, 'utf8');
  if (!text.includes("from '@adqm/gpb-ui'")) violations.push(`${file}: нет импорта @adqm/gpb-ui`);
  if (/<(?:input|select|textarea)\b/.test(text)) violations.push(`${file}: найден нативный form control`);
  if (/className=["'][^"']*\b(?:btn|control)\b/.test(text)) violations.push(`${file}: найден самодельный класс контрола`);
  if (!file.endsWith('ProductShell.tsx') && /<button\b/.test(text)) violations.push(`${file}: найден нативный button вместо Button`);
}
const allTsx = [...readdirSync(join(root, 'pages')).filter((name) => name.endsWith('.tsx')).map((name) => join(root, 'pages', name)), ...readdirSync(join(root, 'components')).filter((name) => name.endsWith('.tsx')).map((name) => join(root, 'components', name))];
for (const file of allTsx) {
  if (file.endsWith('MaterialIcon.tsx')) continue;
  const text = readFileSync(file, 'utf8');
  if (/<svg\b/.test(text)) violations.push(`${file}: найден SVG вне общего MaterialIcon`);
  if (/[☷▷◉⚙◇⌄◌◎▥◫◈⌁]/.test(text)) violations.push(`${file}: найден устаревший символьный значок`);
}
const app = readFileSync(join(root, 'App.tsx'), 'utf8');
const designSystemPage = readFileSync(join(root, 'pages', 'DesignSystemPage.tsx'), 'utf8');
if (!app.includes('DesignSystemPage') || !app.includes("'design-system'") || !designSystemPage.includes('ComponentGallery')) {
  violations.push('страница design-system не подключает библиотечный каталог компонентов');
}
const productPatternPath = join(root, 'components', 'ProductPatternsGallery.tsx');
let productPatterns = '';
try { productPatterns = readFileSync(productPatternPath, 'utf8'); } catch { violations.push('страница design-system не содержит каталог продуктовых паттернов'); }
if (!designSystemPage.includes('ProductPatternsGallery')) violations.push('страница design-system не подключает каталог продуктовых паттернов');
for (const pattern of ['navigation-header', 'monitoring-table', 'source-card', 'wizard-stepper', 'choice-card', 'pipeline-preview', 'summary-panel', 'workspace-picker', 'status-indicators', 'modal-form']) {
  if (!productPatterns.includes(`id="${pattern}"`)) violations.push(`в design-system отсутствует продуктовый паттерн ${pattern}`);
}
const strategiesPage = readFileSync(join(root, 'pages', 'RuleBanksPage.tsx'), 'utf8');
const productStyles = readFileSync(join(root, 'styles.css'), 'utf8');
if (!strategiesPage.includes('MonitoringTable')) violations.push('страница стратегий не использует общую таблицу MonitoringTable');
for (const action of ['Изменить', 'Удалить']) {
  if (!strategiesPage.includes(action)) violations.push(`карточка стратегии не содержит действие «${action}»`);
}
for (const action of ['Изменить', 'Удалить']) {
  if (!new RegExp(`<ActionIcon name="(?:edit|delete)" \\/>${action}`).test(strategiesPage)) violations.push(`действие стратегии «${action}» не имеет видимой подписи`);
}
if (strategiesPage.includes('Запустить бенчмарк')) violations.push('карточка стратегии содержит лишнее действие «Запустить бенчмарк»');
if (strategiesPage.includes('Просмотр')) violations.push('карточка стратегии содержит лишнее действие «Просмотр»');
for (const column of ["{ key: 'method'", "{ key: 'phases'", "{ key: 'usage'"]) {
  if (strategiesPage.includes(column)) violations.push(`таблица стратегий содержит удалённую колонку ${column}`);
}
if (!/\.table-actions\s*\{[^}]*display:\s*(?:flex|inline-flex)/s.test(productStyles)) {
  violations.push('действия строк таблицы не оформлены общим компонентом table-actions');
}
if (violations.length) {
  console.error('UI kit check failed:\n' + violations.map((item) => `- ${item}`).join('\n'));
  process.exit(1);
}
console.log(`UI kit check passed: ${productFiles.length} product files use ADQM GPB UI controls.`);
