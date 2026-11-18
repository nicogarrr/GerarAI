'use client';

import { useT } from '@/lib/i18n/client';

/** Paginador simple y accesible (anterior/siguiente + "página x de y"). */
export function Pager({ page, pages, onPage, total, label }: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
  total: number;
  label: string;
}) {
  const t = useT();
  if (pages <= 1) return null;
  const btn = 'min-h-11 rounded-lg border border-gray-700 px-4 text-sm text-gray-200 transition enabled:hover:border-teal-500 disabled:opacity-40 sm:min-h-9';
  // Móvil 320px (medido en prod, 18-nov): botón + texto + botón no caben en
  // una fila (Siguiente se salía 17px por la derecha, scrollWidth 337). El
  // texto ocupa su propia línea (order-first w-full) y los botones quedan
  // juntos abajo; desde sm vuelve la fila única de siempre.
  return (
    <nav aria-label={t('ui.pagination.ariaOf', { label })} className="mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <button className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)} type="button">{t('ui.pagination.prev')}</button>
      <span aria-live="polite" className="order-first w-full min-w-0 text-center text-xs text-gray-400 sm:order-none sm:w-auto"><span className="whitespace-nowrap">{t('researchShared.pageOf', { current: page, total: pages })}</span> · {total} {label}</span>
      <button className={btn} disabled={page >= pages} onClick={() => onPage(page + 1)} type="button">{t('ui.pagination.next')}</button>
    </nav>
  );
}
