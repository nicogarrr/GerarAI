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
}): PerState {
    const { quoteSymbol, ticker, peTTM, providerAvailable } = input;
    if (!quoteSymbol) return { value: null, note: 'Sin listado de cotización verificado' };
    if (quoteSymbol !== ticker.trim().toUpperCase()) {
        return { value: null, note: 'Cotiza fuera de EE. UU.: sin PER verificable' };
    }
    if (!providerAvailable) return { value: null, note: 'Proveedor de métricas no disponible' };
    if (typeof peTTM === 'number' && Number.isFinite(peTTM) && peTTM > 0) {
        return { value: peTTM, note: 'Finnhub · últimos 12 meses' };
    }
    return { value: null, note: 'El proveedor no informa PER (p. ej. beneficio negativo)' };
}
