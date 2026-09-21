import { ComponentGallery } from '@adqm/gpb-ui';
import { ProductPatternsGallery } from '../components/ProductPatternsGallery';

export function DesignSystemPage(): JSX.Element {
  return <div className="design-system-page"><ProductPatternsGallery /><ComponentGallery backHref="/" backLabel="К DDL Benchmark Engine" /></div>;
}
