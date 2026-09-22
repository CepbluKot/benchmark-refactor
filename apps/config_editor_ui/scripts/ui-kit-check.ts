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
const strategyDimensions = readFileSync(join(root, 'components', 'StrategyDimensionsEditor.tsx'), 'utf8');
if (!strategiesPage.includes('MonitoringTable')) violations.push('страница стратегий не использует общую таблицу MonitoringTable');
for (const action of ['Изменить', 'Удалить']) {
  if (!strategiesPage.includes(`t('${action}'`)) violations.push(`карточка стратегии не содержит локализованное действие «${action}»`);
}
for (const action of ['Изменить', 'Удалить']) {
  if (!new RegExp(`<ActionIcon name="(?:edit|delete)" \\/>\\{t\\('${action}'`).test(strategiesPage)) violations.push(`действие стратегии «${action}» не имеет локализованной видимой подписи`);
}
if (strategiesPage.includes('Запустить бенчмарк')) violations.push('карточка стратегии содержит лишнее действие «Запустить бенчмарк»');
if (strategiesPage.includes('Просмотр')) violations.push('карточка стратегии содержит лишнее действие «Просмотр»');
for (const column of ["{ key: 'method'", "{ key: 'phases'", "{ key: 'usage'"]) {
  if (strategiesPage.includes(column)) violations.push(`таблица стратегий содержит удалённую колонку ${column}`);
}
if (!/\.table-actions\s*\{[^}]*display:\s*(?:flex|inline-flex)/s.test(productStyles)) {
  violations.push('действия строк таблицы не оформлены общим компонентом table-actions');
}
if (!strategyDimensions.includes('className="strategy-add"')) violations.push('кнопки добавления в редакторе стратегий не имеют семантический класс strategy-add');
if (!/\.product-root\s+\.button\.strategy-add\s*\{[^}]*color:/s.test(productStyles)) violations.push('конструктивный цвет кнопок добавления не перекрывает базовый secondary-стиль');
if (!/\.product-root\s+\.button\.strategy-remove\s*\{[^}]*border-color:\s*var\(--danger\)/s.test(productStyles)) violations.push('danger-стиль кнопок удаления не перекрывает базовый secondary-стиль');
if (!/\.product-root\s+\.button\.strategy-add\s*\{[^}]*background:\s*var\(--acm-accent\)\s*!important/s.test(productStyles)) violations.push('кнопки добавления должны авторитетно перекрывать фон secondary-кнопки');
if (!/\.product-root\s+\.button\.strategy-add\s*\{[^}]*display:\s*inline-flex[^}]*align-items:\s*center[^}]*justify-content:\s*center/s.test(productStyles)) violations.push('кнопки добавления должны центрировать иконку и подпись в одной строке');
if (!/\.product-root\s+\.button\.strategy-remove\s*\{[^}]*background:\s*var\(--danger\)\s*!important/s.test(productStyles)) violations.push('кнопки удаления должны авторитетно перекрывать фон secondary-кнопки');
if (violations.length) {
  console.error('UI kit check failed:\n' + violations.map((item) => `- ${item}`).join('\n'));
  process.exit(1);
}
console.log(`UI kit check passed: ${productFiles.length} product files use ADQM GPB UI controls.`);
