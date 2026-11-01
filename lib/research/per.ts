// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';

/**
 * PER (TTM) de la ficha: solo con dato verificable. Finnhub se pide únicamente
 * para el listado US del propio emisor (en uno no-US sería del ADR o de un
 * homónimo, ver quote-symbol.ts). Sin dato, el motivo es explícito.
 */
export type PerState = { value: number | null; note: string | null };

export function perState(input: {
    /** Símbolo de cotización del listado real (quoteSymbolFor) o null. */
    quoteSymbol: string | null;
    ticker: string;
    /** metric.peTTM de Finnhub; undefined si la petición no devolvió métricas. */
    peTTM: unknown;
    providerAvailable: boolean;
    /** Linea US derivada de bolsa/divisa (isUsQuoteLine). Si se informa manda sobre la igualdad simbolo==ticker. */
    usLine?: boolean;
}, locale: 'es' | 'en' = 'es'): PerState {
    const { quoteSymbol, ticker, peTTM, providerAvailable, usLine } = input;
    const t = createTranslator(locale);
    if (!quoteSymbol) return { value: null, note: t('research.per.noListing') };
    if (usLine === false || quoteSymbol !== ticker.trim().toUpperCase()) {
        return { value: null, note: t('research.per.nonUs') };
    }
    if (!providerAvailable) return { value: null, note: t('research.per.providerDown') };
    if (typeof peTTM === 'number' && Number.isFinite(peTTM) && peTTM > 0) {
        return { value: peTTM, note: t('research.per.ttm') };
    }
    return { value: null, note: t('research.per.notReported') };
}
