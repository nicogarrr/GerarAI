/**
 * Símbolo de cotización del LISTADO REAL, o null (sin precio).
 *
 * Finnhub free y FMP `/quote` resuelven el ticker pelado en bolsas US: para
 * un emisor no-US devuelven el gemelo americano — otro emisor (ALM de
 * Almirall/BME -> Almonty en Nasdaq) o el ADR en USD del mismo emisor
 * (ASML). Sin identidad de listado verificada (master inaccesible) o sin
 * correspondencia de bolsa validada, la respuesta honesta es «cotización no
 * disponible» — nunca el ticker desnudo, que puede cotizar a otro emisor.
 */

export type ListingBasics = { exchange?: string; currency?: string } | null | undefined;

const US_EXCHANGE_TOKENS = ['NYSE', 'NEW YORK', 'NASDAQ', 'AMEX', 'BATS', 'ARCA', 'OTC'];

const EXCHANGE_YAHOO_SUFFIX: Record<string, string> = {
    BME: '.MC',
    'BOLSA DE MADRID': '.MC',
    'NYSE EURONEXT - EURONEXT AMSTERDAM': '.AS',
    'TORONTO STOCK EXCHANGE': '.TO',
    'SWISS EXCHANGE': '.SW',
    // XETRA -> .DE verificado contra Yahoo chart API 2026-09-27 (SAP.DE:
    // exchange GER, EUR). Ampliar el mapa exige la misma evidencia.
    XETRA: '.DE',
};

export function quoteSymbolFor(company: ListingBasics, rawTicker: string): string | null {
    if (!company) return null;
    // Los simbolos de cotizacion van siempre en mayusculas y sin espacios: un
    // ticker en minusculas ('aapl') no puede producir un simbolo distinto ni
    // hacer que isUsQuoteLine lo trate como linea no-US.
    const ticker = rawTicker.trim().toUpperCase();
    const exchange = (company.exchange || '').toUpperCase();
    const currency = (company.currency || '').toUpperCase();
    // El mapa exacto de plazas no-US manda sobre la inferencia por subcadena:
    // «NYSE EURONEXT - EURONEXT AMSTERDAM» CONTIENE «NYSE», y con la divisa
    // ausente (estado de datos permitido) la inferencia US devolvía el ticker
    // pelado — el ADR en USD — antes que la línea .AS verificada.
    // Londres: solo si el ticker YA es el simbolo del listado (CGEO.L, verificado
    // contra Yahoo chart API 2026-10-19: LSE, GBp). Nunca se adivina el sufijo
    // de un ticker pelado (AZN, SHEL): el gemelo US no es el instrumento .L.
    if (exchange.includes('LONDON') || exchange === 'LSE') {
        return /^[A-Z0-9]+\.L$/i.test(ticker) ? ticker.toUpperCase() : null;
    }
    const suffix = EXCHANGE_YAHOO_SUFFIX[exchange];
    if (suffix) {
        // Un ticker guardado ya con el sufijo de su plaza (ITX.MC, SAP.DE, que
        // es como lo devuelve el buscador) es el símbolo de listado: añadir el
        // sufijo otra vez daba ITX.MC.MC, sin cotización ni logo (404).
        return ticker.endsWith(suffix) ? ticker : `${ticker}${suffix}`;
    }
    const usExchange =
        exchange !== '' &&
        exchange !== 'UNKNOWN' &&
        // Ninguna plaza Euronext es un listado US: la nomenclatura histórica
        // de Finnhub («NYSE EURONEXT - ...») no abre la vía del ticker pelado.
        !exchange.includes('EURONEXT') &&
        US_EXCHANGE_TOKENS.some((token) => exchange.includes(token));
    // Listado US: la divisa USD es la evidencia (bulk import americano con
    // bolsa UNKNOWN); a falta de divisa sirve una bolsa US conocida.
    if (currency === 'USD' && (exchange === '' || exchange === 'UNKNOWN' || usExchange)) {
        return ticker;
    }
    if (currency === '' && usExchange) {
        return ticker;
    }
    // No-US sin correspondencia validada: null — ni ticker desnudo (gemelo
    // US) ni sufijo adivinado (EUR->.MC podría cotizar un homónimo español).
    return null;
}

/**
 * true solo para la LINEA US del emisor (la unica cuyas metricas Finnhub y
 * cuya unidad USD son de ESTE listado). Se deriva de la bolsa/divisa, NO de
 * `quoteSymbol === ticker`: un ticker que ya es simbolo de listado no-US
 * (CGEO.L) tambien cumple esa igualdad y cotiza en peniques (GBX).
 */
export function isUsQuoteLine(company: ListingBasics, ticker: string): boolean {
    const symbol = quoteSymbolFor(company, ticker);
    if (!symbol || symbol !== ticker.trim().toUpperCase()) return false;
    const exchange = (company?.exchange || '').toUpperCase();
    if (exchange.includes('LONDON') || exchange === 'LSE') return false;
    if (EXCHANGE_YAHOO_SUFFIX[exchange]) return false;
    return true;
}
