import Link from 'next/link';

import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { TABS, tabHref, tabOfView, type TabKey, type View } from '@/lib/research/research-views';

/** Nombre visible de cada pestaña (la clave y el `?view=` no cambian). */
const TAB_LABEL_KEYS = {
  resumen: 'research.tabs.resumen',
  tesis: 'research.tabs.tesis',
  finanzas: 'research.tabs.finanzas',
  valoracion: 'research.tabs.valoracion',
  seguimiento: 'research.tabs.seguimiento',
  fuentes: 'research.tabs.fuentes',
} as const satisfies Record<TabKey, string>;

/**
 * Navegación de la ficha de empresa: UNA fila de seis pestañas (decisión de
 * Nico, 29-oct-2026, opción 1 de «Una fila, no tres menús»). Sin fila de
 * módulos ni cajón «Análisis avanzado»: los módulos son secciones ancladas
 * dentro de cada pestaña, a un toque desde esta fila.
 *
 * Móvil primero: la fila se desliza en horizontal si no cabe (scroll
 * nativo, sin botones); desde sm sobra sitio para las seis. `scroll={false}`
 * porque todas las pestañas son la MISMA ruta con otro `?view=`: sin el
 * atributo Next devolvía al usuario al inicio de la página (bug del
 * 19-oct-2026). La marca teal fina dice «estás aquí», como la barra del
 * sidebar.
 */
export function CompanyNavigation({ ticker, activeView, locale = 'es' }: { ticker: string; activeView: View; locale?: Locale }) {
  const activeTab = tabOfView(activeView);
  const t = createTranslator(locale);
  return (
    <nav
      aria-label={t('research.companyNav.aria')}
      className="-mx-1 flex gap-x-1 overflow-x-auto px-1 pb-px sm:gap-x-2"
      data-testid="company-navigation"
    >
      {TABS.map((tab) => (
        <Link
          aria-current={activeTab === tab.key ? 'page' : undefined}
          className={`inline-flex min-h-[44px] shrink-0 items-center whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition ${activeTab === tab.key ? 'border-teal-300 text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-200'}`}
          href={tabHref(ticker, tab.key)}
          key={tab.key}
          scroll={false}
        >
          {t(TAB_LABEL_KEYS[tab.key])}
        </Link>
      ))}
    </nav>
  );
}
