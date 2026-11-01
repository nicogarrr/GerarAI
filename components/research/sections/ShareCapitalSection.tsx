import { MutationForm } from '@/components/forms/MutationForm';
import { refreshCompanyFinancialsSEC } from '@/lib/actions/research.actions';
import type { ShareCapital } from '@/lib/actions/share-capital.actions';
import { ShareCapitalPanel } from '@/components/research/ShareCapitalPanel';
import { Button } from '@/components/ui/button';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/**
 * Dilución y recompras como sección de la pestaña Finanzas (antes página
 * propia `/share-capital`, que ahora redirige aquí). Mismo panel y misma
 * acción de refresco SEC que la página histórica.
 */
export function ShareCapitalSection({ ticker, data, locale = DEFAULT_LOCALE }: { ticker: string; data: ShareCapital | null; locale?: Locale }) {
  const t = createTranslator(locale);
  return <div className="grid gap-4">
    <div className="flex flex-wrap gap-3">
      <MutationForm action={refreshCompanyFinancialsSEC.bind(null, ticker)} successMessage={t('research.shareCapital.refreshedSec')}><Button type="submit" variant="outline">{t('research.shareCapital.refreshSec')}</Button></MutationForm>
    </div>
    {data ? <ShareCapitalPanel data={data} /> : <p className="text-sm text-gray-400" role="status">{t('research.shareCapital.sectionEmpty')}</p>}
  </div>;
}
