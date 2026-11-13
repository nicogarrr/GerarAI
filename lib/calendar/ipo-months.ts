/**
 * Meses del calendario IPO: el backend (ipo_calendar.py) los nombra en
 * castellano ("noviembre", "diciembre") y la página los interpola tal cual.
 * En inglés se traducen por índice con Intl — la tabla ES se deriva del
 * propio Intl, sin literales escritos a mano — y un nombre que no se
 * reconoce pasa tal cual (nunca se oculta un dato de la fuente).
 */
import type { Locale } from '@/lib/i18n/locale';

const monthName = (index: number, locale: Locale): string =>
    new Intl.DateTimeFormat(locale, { month: 'long' }).format(new Date(2024, index, 1));

const ES_MONTH_INDEX: Record<string, number> = Object.fromEntries(
    Array.from({ length: 12 }, (_, index) => [monthName(index, 'es'), index]),
);

/** Lista de meses del backend en el idioma activo, separados por comas. */
export function ipoMonthsLabel(months: string[], locale: Locale): string {
    if (locale !== 'en') return months.join(', ');
    return months
        .map((name) => {
            const index = ES_MONTH_INDEX[name.toLowerCase()];
            return index === undefined ? name : monthName(index, 'en');
        })
        .join(', ');
}
