/**
 * Divisa con la que la cabecera de precio puede rotular el último cierre del
 * gráfico cuando no hay cotización en vivo (realqa-18, CGEO.L).
 *
 * Las velas no traen divisa propia: se rotulan con la divisa del listado, la
 * misma que usa el gráfico (`snapshot.currency`). En un listado en subunidad
 * (LSE en peniques, .JO en céntimos, .TA en agorot) eso solo es correcto si el
 * maestro declara ya la subunidad (GBX/ZAC/ILA): entonces velas, gráfico y
 * cabecera hablan de la misma escala. Si declara la unidad grande (GBP en un
 * .L) la escala es ambigua (x100) y se devuelve null: la cabecera queda en N/D
 * antes que pintar 4.215 £ por 42,15 £.
 */
const SUBUNIT_CURRENCIES = new Set(['GBX', 'ZAC', 'ILA']);

/** Normaliza los códigos de subunidad de Yahoo (GBp, ZAc) a su forma mostrable. */
export function normalizeSubunitCurrency(currency: string | null | undefined): string | null {
    if (!currency) return null;
    if (currency === 'GBp') return 'GBX';
    if (currency === 'ZAc') return 'ZAC';
    return currency;
}

export function isSubunitListing(input: { ticker: string; symbol?: string | null; exchange?: string | null; currency?: string | null }): boolean {
    const currency = normalizeSubunitCurrency(input.currency);
    return /\.(L|JO|TA)$/i.test(input.symbol ?? input.ticker)
        || /LONDON|^LSE$|JOHANNESBURG|TEL AVIV/i.test(input.exchange ?? '')
        || (currency != null && SUBUNIT_CURRENCIES.has(currency));
}

/**
 * null = no hay divisa fiable para rotular el cierre de las velas (sin fallback).
 *
 * `candleCurrency` es la divisa que el proveedor declara en la MISMA respuesta de
 * velas (Yahoo `meta.currency`). En un listado en subunidad es obligatoria y debe
 * coincidir con el maestro (tras normalizar GBp->GBX): si falta o discrepa, la
 * escala (x100) no se puede probar y la cabecera queda en N/D. En el resto de
 * listados, una divisa de velas que discrepa del maestro también anula el
 * fallback; si no la trae (Finnhub), se mantiene el comportamiento anterior.
 */
export function chartFallbackCurrency(input: { ticker: string; symbol?: string | null; exchange?: string | null; currency?: string | null; candleCurrency?: string | null }): string | null {
    const currency = normalizeSubunitCurrency(input.currency);
    if (!currency || !/^[A-Z]{3}$/.test(currency)) return null;
    const candle = normalizeSubunitCurrency(input.candleCurrency);
    if (candle != null && candle !== currency) return null;
    if (!isSubunitListing(input)) return currency;
    if (!SUBUNIT_CURRENCIES.has(currency)) return null;
    return candle === currency ? currency : null;
}
