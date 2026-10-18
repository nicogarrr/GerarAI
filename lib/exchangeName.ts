/**
 * F156: el `exchange` que llega del enriquecimiento (Finnhub) usa su propia
 * nomenclatura con subdivisiones que NO son verificables («NASDAQ NMS -
 * GLOBAL MARKET» para PARA, cuyo 8-K declara Nasdaq Capital Market). La UI
 * muestra solo el mercado, sin la subdivisión que la fuente no garantiza.
 * Devuelve null cuando no hay mercado conocido que mostrar.
 */
const EXCHANGE_ALIASES: Array<[RegExp, string]> = [
    [/NASDAQ/i, 'NASDAQ'],
    [/NEW YORK STOCK EXCHANGE|^NYSE$/i, 'NYSE'],
    [/NYSE\s*(MKT|AMERICAN)/i, 'NYSE American'],
    [/BME|BOLSA DE MADRID/i, 'BME'],
    [/TORONTO/i, 'TSX'],
    [/SWISS/i, 'SIX'],
    [/OTC/i, 'OTC'],
    // «NYSE EURONEXT - ...» es la nomenclatura histórica de Finnhub para las
    // plazas Euronext (herencia de cuando NYSE poseía Euronext): NO es NYSE.
    // Mostrar «NYSE» para ASML (Amsterdam) hacía incoherente el par
    // bolsa/divisa (F180). La ciudad la garantiza la propia cadena.
    // La tabla se evalúa en orden inverso: la regla genérica va ANTES para
    // que las plazas con ciudad ganen.
    [/EURONEXT/i, 'Euronext'],
    [/EURONEXT AMSTERDAM/i, 'Euronext Amsterdam'],
    [/EURONEXT PARIS/i, 'Euronext Paris'],
    [/EURONEXT BRUSSELS/i, 'Euronext Brussels'],
    [/EURONEXT LISBON/i, 'Euronext Lisbon'],
];

export function exchangeDisplayName(raw: string | null | undefined): string | null {
    const value = raw?.trim();
    if (!value || value.toUpperCase() === 'UNKNOWN' || value.toUpperCase() === 'UNKNOWN_EXCHANGE' || /^[A-Z]$/i.test(value)) {
        return null;
    }
    // NYSE MKT/American antes que NYSE a secas (orden de la tabla).
    for (const [pattern, name] of [...EXCHANGE_ALIASES].reverse()) {
        if (pattern.test(value)) return name;
    }
    return value;
}
