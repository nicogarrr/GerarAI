/**
 * Texto del estado vacío de Acciones Corporativas. "Todo al día" solo sería
 * cierto con una fuente operativa; sin importaciones registradas se dice que
 * no hay fuente, y con ellas se da la fecha de la última importación.
 * Con la app en inglés (Ajustes → Idioma) el texto y la fecha van en inglés.
 */
import type { Locale } from '../i18n/locale.ts';

export function corporateActionsEmptyMessage(
    status: { dividends_last_import: string | null; splits_last_import: string | null } | null,
    locale: Locale = 'es',
): string {
    const en = locale === 'en';
    if (!status) {
        return en
            ? 'No events and no source status right now. Try again in a few seconds.'
            : 'Sin eventos y sin estado de las fuentes ahora mismo. Reintenta en unos segundos.';
    }
    const dates = [status.dividends_last_import, status.splits_last_import]
        .filter((value): value is string => Boolean(value))
        .map((value) => new Date(value))
        .filter((value) => !Number.isNaN(value.getTime()));
    if (dates.length === 0) {
        return en
            ? 'No events: no dividends or splits have been imported yet.'
            : 'Sin eventos: todavía no se ha importado ningún dividendo ni split.';
    }
    const last = new Date(Math.max(...dates.map((value) => value.getTime())));
    const day = last.toLocaleDateString(en ? 'en-US' : 'es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Madrid' });
    return en ? `No pending events. Last data import: ${day}.` : `Sin eventos pendientes. Última importación de datos: ${day}.`;
}
