import Link from 'next/link';

/** Pagina `items` dentro de la propia pagina (sin scroll infinito). `pagina` fuera de rango se acota. */
export function paginate<T>(items: T[], pageParam: string | undefined, size: number) {
    const total = Math.max(1, Math.ceil(items.length / size));
    const parsed = Number.parseInt(pageParam ?? '1', 10);
    const page = Number.isFinite(parsed) ? Math.min(Math.max(1, parsed), total) : 1;
    return { page, total, items: items.slice((page - 1) * size, page * size) };
}

type PaginationProps = {
    page: number;
    total: number;
    basePath: string;
    /** Parametros que se conservan al cambiar de pagina (p. ej. `vista`). */
    params?: Record<string, string>;
};

function pageHref(basePath: string, page: number, params: Record<string, string>): string {
    const query = new URLSearchParams(params);
    if (page > 1) query.set('pagina', String(page));
    const text = query.toString();
    return text ? `${basePath}?${text}` : basePath;
}

export function Pagination({ page, total, basePath, params = {} }: PaginationProps) {
    if (total <= 1) return null;
    const linkClass = 'inline-flex min-h-[44px] items-center rounded-lg border border-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:border-gray-700 sm:min-h-0';
    const offClass = 'rounded-lg border border-gray-900 px-3 py-1.5 text-sm text-gray-700';
    return (
        <nav aria-label="Paginación" className="flex items-center justify-between gap-4">
            {page > 1 ? (
                <Link className={linkClass} href={pageHref(basePath, page - 1, params)} rel="prev">
                    Anterior
                </Link>
            ) : (
                <span aria-disabled="true" className={offClass}>Anterior</span>
            )}
            <span className="text-sm text-gray-500">
                Página {page} de {total}
            </span>
            {page < total ? (
                <Link className={linkClass} href={pageHref(basePath, page + 1, params)} rel="next">
                    Siguiente
                </Link>
            ) : (
                <span aria-disabled="true" className={offClass}>Siguiente</span>
            )}
        </nav>
    );
}
