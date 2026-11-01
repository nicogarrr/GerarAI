import { EmptyState } from '@/components/ui/empty-state';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/**
 * Aviso inline de una sección de la ficha cuya lectura falló: nunca vacío
 * fingido ni pestaña entera caída. Reintentar recarga la pestaña en su ancla.
 */
export function SectionLoadError({ retryHref, title, locale = DEFAULT_LOCALE }: { retryHref: string; title: string; locale?: Locale }) {
  const t = createTranslator(locale);
  return (
    <div className="space-y-3">
      <EmptyState title={t('research.sectionLoadError', { title })} />
      <a
        className="inline-flex min-h-[44px] items-center rounded-lg border border-gray-700 px-4 text-sm text-teal-300 hover:border-teal-700 hover:text-teal-200"
        href={retryHref}
      >
        {t('common.actions.retry')}
      </a>
    </div>
  );
}
