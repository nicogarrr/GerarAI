/**
 * Texto del estado vacío de Acciones Corporativas. "Todo al día" solo sería
 * cierto con una fuente operativa; sin importaciones registradas se dice que
 * no hay fuente, y con ellas se da la fecha de la última importación.
 * Con la app en inglés (Ajustes → Idioma) el texto y la fecha van en inglés.
 */
import type { Locale } from '../i18n/locale.ts';
// @ts-expect-error TS5097: Node strip-types requires explicit extension.
import { createTranslator, type TranslateFn } from '../i18n/translate.ts';

export function corporateActionsEmptyMessage(
    status: { dividends_last_import: string | null; splits_last_import: string | null } | null,
    locale: Locale = 'es',
    t: TranslateFn = createTranslator(locale),
): string {
    const en = locale === 'en';
    if (!status) {
        return t('corporateActions.empty.noStatus');
    }
    const dates = [status.dividends_last_import, status.splits_last_import]
        .filter((value): value is string => Boolean(value))
        .map((value) => new Date(value))
        .filter((value) => !Number.isNaN(value.getTime()));
    if (dates.length === 0) {
        return t('corporateActions.empty.noImports');
    }
    const last = new Date(Math.max(...dates.map((value) => value.getTime())));
    const day = last.toLocaleDateString(en ? 'en-US' : 'es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Madrid' });
    return t('corporateActions.empty.lastImport', { day });
}
