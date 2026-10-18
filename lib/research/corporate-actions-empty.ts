/**
 * Texto del estado vacío de Acciones Corporativas. "Todo al día" solo sería
 * cierto con una fuente operativa; sin importaciones registradas se dice que
 * no hay fuente, y con ellas se da la fecha de la última importación.
 */
export function corporateActionsEmptyMessage(
    status: { dividends_last_import: string | null; splits_last_import: string | null } | null,
): string {
    if (!status) return 'Sin eventos y sin estado de las fuentes ahora mismo. Reintenta en unos segundos.';
    const dates = [status.dividends_last_import, status.splits_last_import]
        .filter((value): value is string => Boolean(value))
        .map((value) => new Date(value))
        .filter((value) => !Number.isNaN(value.getTime()));
    if (dates.length === 0) {
        return 'Sin eventos: todavía no se ha importado ningún dividendo ni split.';
    }
    const last = new Date(Math.max(...dates.map((value) => value.getTime())));
    const day = last.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Madrid' });
    return `Sin eventos pendientes. Última importación de datos: ${day}.`;
}
