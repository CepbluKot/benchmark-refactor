import { ComponentGallery } from '@adqm/gpb-ui';
import { ProductPatternsGallery } from '../components/ProductPatternsGallery';
import { useI18n } from '../i18n';

export function DesignSystemPage(): JSX.Element {
  const { t } = useI18n();
  return <div className="design-system-page"><ProductPatternsGallery /><ComponentGallery backHref="/" backLabel={t('К DB Benchmark', 'Back to DB Benchmark')} /></div>;
}
