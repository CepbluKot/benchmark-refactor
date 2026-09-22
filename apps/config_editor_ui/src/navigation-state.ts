export type ProductPage = 'sources' | 'benchmarks' | 'create-benchmark' | 'edit-benchmark' | 'runs' | 'strategies' | 'create-strategy' | 'edit-strategy' | 'design-system';

const topLevelPages = new Set<ProductPage>(['sources', 'benchmarks', 'runs', 'strategies', 'design-system']);
const parentPages: Partial<Record<ProductPage, ProductPage>> = {
  'create-benchmark': 'benchmarks',
  'edit-benchmark': 'benchmarks',
  'create-strategy': 'strategies',
  'edit-strategy': 'strategies',
};

export const PRODUCT_PAGE_STORAGE_KEY = 'db-benchmark-last-page';

export function savedProductPage(page: ProductPage): ProductPage {
  return parentPages[page] ?? page;
}

export function restoreProductPage(value: string | null): ProductPage {
  return value !== null && topLevelPages.has(value as ProductPage) ? value as ProductPage : 'benchmarks';
}

export function productPageFromUrl(url: string): ProductPage {
  try { return restoreProductPage(new URL(url).searchParams.get('page')); } catch { return 'benchmarks'; }
}
