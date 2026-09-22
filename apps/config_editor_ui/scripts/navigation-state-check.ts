import { productPageFromUrl, restoreProductPage, savedProductPage } from '../src/navigation-state';

const expect = (actual: unknown, expected: unknown, label: string): void => {
  if (actual !== expected) throw new Error(`${label}: expected ${String(expected)}, got ${String(actual)}`);
};

expect(savedProductPage('create-benchmark'), 'benchmarks', 'create benchmark saves its parent');
expect(savedProductPage('edit-strategy'), 'strategies', 'edit strategy saves its parent');
expect(savedProductPage('runs'), 'runs', 'top-level page is unchanged');
expect(restoreProductPage('strategies'), 'strategies', 'saved top-level page is restored');
expect(restoreProductPage('create-strategy'), 'benchmarks', 'temporary page is not restored');
expect(restoreProductPage('unknown'), 'benchmarks', 'unknown value falls back safely');
expect(productPageFromUrl('http://127.0.0.1:18901/?v=guided-options&page=strategies'), 'strategies', 'URL page takes precedence');
expect(productPageFromUrl('http://127.0.0.1:18901/?page=unknown'), 'benchmarks', 'invalid URL page falls back safely');

console.log('Navigation state checks passed');
