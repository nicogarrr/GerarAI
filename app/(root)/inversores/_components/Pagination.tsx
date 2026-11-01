import { PaginationNav } from './PaginationNav';

/** Pagina `items` dentro de la propia pagina (sin scroll infinito). `pagina` fuera de rango se acota. */
export function paginate<T>(items: T[], pageParam: string | undefined, size: number) {
    const total = Math.max(1, Math.ceil(items.length / size));
    const parsed = Number.parseInt(pageParam ?? '1', 10);
    const page = Number.isFinite(parsed) ? Math.min(Math.max(1, parsed), total) : 1;
    return { page, total, items: items.slice((page - 1) * size, page * size) };
}

export type PaginationProps = {
    page: number;
    total: number;
    basePath: string;
    /** Parametros que se conservan al cambiar de pagina (p. ej. `vista`). */
    params?: Record<string, string>;
};

export function Pagination(props: PaginationProps) {
    if (props.total <= 1) return null;
    return <PaginationNav {...props} />;
}
