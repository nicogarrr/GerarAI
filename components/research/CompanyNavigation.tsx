import Link from 'next/link';

import { TABS, tabHref, tabOfView, type View } from '@/lib/research/research-views';

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
export function CompanyNavigation({ ticker, activeView }: { ticker: string; activeView: View }) {
  const activeTab = tabOfView(activeView);
  return (
    <nav
      aria-label="Secciones de la empresa"
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
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
