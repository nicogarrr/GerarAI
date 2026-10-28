'use client';

/** Paginador simple y accesible (anterior/siguiente + "página x de y"). */
export function Pager({ page, pages, onPage, total, label }: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
  total: number;
  label: string;
}) {
  if (pages <= 1) return null;
  const btn = 'min-h-11 rounded-lg border border-gray-700 px-4 text-sm text-gray-200 transition enabled:hover:border-teal-500 disabled:opacity-40 sm:min-h-9';
  return (
    <nav aria-label={`Paginación de ${label}`} className="mt-4 flex items-center justify-between gap-3">
      <button className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)} type="button">Anterior</button>
      <span aria-live="polite" className="text-xs text-gray-400">Página {page} de {pages} · {total} {label}</span>
      <button className={btn} disabled={page >= pages} onClick={() => onPage(page + 1)} type="button">Siguiente</button>
    </nav>
  );
}
