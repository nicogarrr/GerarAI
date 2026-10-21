/**
 * Panel /mercados: catalogo y parseo de cotizaciones "casi en tiempo" via
 * Yahoo Finance chart API (gratuita, sin key; la misma fuente que ya usa el
 * backend en data-engine/app/api/routes/market.py).
 *
 * Reglas de honestidad del modulo:
 * - Nunca se inventa un cambio: sin cierre previo del proveedor, change y
 *   changePercent son null y la UI pinta "N/D".
 * - La unidad la fija el CATALOGO (unit), no la divisa que devuelva Yahoo:
 *   un indice son puntos, no dolares (F152). `currency` solo se conserva
 *   como dato informativo.
 * - Cada cotizacion lleva el timestamp del proveedor; la UI muestra esa hora
 *   (Madrid) y el aviso de retraso. Nada se etiqueta como "tiempo real".
 *
 * Modulo PURO: sin imports de servidor, para probarlo con node --test.
 *
 * CONDICIONES DE LA FUENTE (estado a 21-oct-2026):
 * - Yahoo Finance chart API es un endpoint publico SIN documentacion ni
 *   licencia oficial: no hay SLA, ni terminos claros de redistribucion, ni
 *   garantia de continuidad. Tratarlo como proveedor de produccion es un
 *   RIESGO PENDIENTE, no una decision cerrada: si Yahoo corta o limita,
 *   este panel pasa a N/D sin romper nada mas (fallo aislado por simbolo).
 * - La hora de cada cotizacion es la que Yahoo ATRIBUYE al dato
 *   (regularMarketTime). No prueba el retraso real del feed ni es una
 *   garantia de tiempo real; la UI la presenta como "hora del dato".
 * - Los futuros/materias primas son series continuas de Yahoo: la fuente
 *   no informa el vencimiento del contrato concreto y no lo inferimos.
 */

export type LiveQuoteKind = 'indice' | 'futuro' | 'accion' | 'materia' | 'divisa';

/** 'index' = puntos de indice (sin unidad monetaria); el resto son divisas ISO. */
export type LiveQuoteUnit = 'index' | 'EUR' | 'USD' | 'cruz';

export interface LiveQuoteSpec {
    /** Simbolo tal cual lo espera la chart API de Yahoo. */
    symbol: string;
    /** Nombre visible en espanol. */
    name: string;
    kind: LiveQuoteKind;
    unit: LiveQuoteUnit;
    /**
     * Unidad real y visible de la cifra ('puntos', 'EUR/acción',
     * 'USD/onza troy', 'USD/barril', 'USD/libra', ...). La fija el
     * catalogo, no Yahoo: el cobre cotiza en USD/libra, no en "USD".
     */
    unitLabel: string;
}

export interface LiveQuote extends LiveQuoteSpec {
    price: number;
    /** null = sin cierre previo del proveedor: cambio no medible. */
    change: number | null;
    changePercent: number | null;
    /** Epoch segundos, segun Yahoo. */
    timestamp: number | null;
    /** Divisa que informa Yahoo (informativa; no fija la unidad). */
    currency: string | null;
    /** Estado del mercado segun Yahoo (REGULAR, PRE, POST, CLOSED...); null si no lo informa. */
    marketState: string | null;
    /** Mercado/centro segun Yahoo (informativo). */
    exchangeName: string | null;
}

/** Meta de la chart API de Yahoo: solo los campos que leemos. */
export interface YahooChartMeta {
    regularMarketPrice?: number | null;
    previousClose?: number | null;
    chartPreviousClose?: number | null;
    regularMarketTime?: number | null;
    currency?: string | null;
    marketState?: string | null;
    exchangeName?: string | null;
    fullExchangeName?: string | null;
}

const isFiniteNumber = (value: unknown): value is number =>
    typeof value === 'number' && Number.isFinite(value);

/**
 * Convierte el meta de Yahoo en una LiveQuote, o null si no hay precio
 * utilizable (la UI pinta N/D para ese valor, nunca un 0 inventado).
 */
export function parseYahooQuote(spec: LiveQuoteSpec, meta: YahooChartMeta | null | undefined): LiveQuote | null {
    if (!meta || !isFiniteNumber(meta.regularMarketPrice) || meta.regularMarketPrice <= 0) return null;
    const prevClose = isFiniteNumber(meta.previousClose) && meta.previousClose > 0
        ? meta.previousClose
        : isFiniteNumber(meta.chartPreviousClose) && meta.chartPreviousClose > 0
            ? meta.chartPreviousClose
            : null;
    const change = prevClose === null ? null : meta.regularMarketPrice - prevClose;
    const changePercent = prevClose === null ? null : (meta.regularMarketPrice - prevClose) / prevClose * 100;
    return {
        ...spec,
        price: meta.regularMarketPrice,
        change,
        changePercent,
        timestamp: isFiniteNumber(meta.regularMarketTime) ? meta.regularMarketTime : null,
        currency: typeof meta.currency === 'string' ? meta.currency : null,
        marketState: typeof meta.marketState === 'string' ? meta.marketState : null,
        exchangeName:
            typeof meta.fullExchangeName === 'string'
                ? meta.fullExchangeName
                : typeof meta.exchangeName === 'string'
                    ? meta.exchangeName
                    : null,
    };
}

export const YAHOO_CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart';

export function yahooChartRequest(symbol: string): { url: string; init: RequestInit } {
    return {
        url: `${YAHOO_CHART_URL}/${encodeURIComponent(symbol)}?range=2d&interval=1d`,
        init: {
            headers: {
                // Sin UA de navegador Yahoo responde 429/403 a peticiones de servidor.
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
                Accept: 'application/json',
            },
        },
    };
}

/* ------------------------------------------------------------------ *
 * Catalogo: solo simbolos verificados contra la chart API (21-oct-2026,
 * los ~40 devolvieron precio y timestamp). Anadir uno nuevo exige la
 * misma verificacion y actualizar el guard live-quotes-guard.test.ts.
 * ------------------------------------------------------------------ */

export const LIVE_INDICES: LiveQuoteSpec[] = [
    { symbol: '^GSPC', name: 'S&P 500', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^IXIC', name: 'Nasdaq Composite', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^DJI', name: 'Dow Jones', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^RUT', name: 'Russell 2000', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^IBEX', name: 'IBEX 35', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^STOXX50E', name: 'Euro Stoxx 50', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^GDAXI', name: 'DAX', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^FTSE', name: 'FTSE 100', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^FCHI', name: 'CAC 40', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^N225', name: 'Nikkei 225', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
    { symbol: '^VIX', name: 'VIX (volatilidad S&P 500)', kind: 'indice', unit: 'index', unitLabel: 'puntos' },
];

export const LIVE_FUTURES: LiveQuoteSpec[] = [
    { symbol: 'ES=F', name: 'Futuro S&P 500 (E-mini)', kind: 'futuro', unit: 'index', unitLabel: 'puntos' },
    { symbol: 'NQ=F', name: 'Futuro Nasdaq 100 (E-mini)', kind: 'futuro', unit: 'index', unitLabel: 'puntos' },
    { symbol: 'YM=F', name: 'Futuro Dow Jones (mini)', kind: 'futuro', unit: 'index', unitLabel: 'puntos' },
    { symbol: 'RTY=F', name: 'Futuro Russell 2000 (E-mini)', kind: 'futuro', unit: 'index', unitLabel: 'puntos' },
];

/**
 * Seleccion fija de valores liquidos del IBEX 35. NO es un ranking por
 * volumen: sin una fuente gratuita de "mas negociadas" no se puede
 * sostener esa etiqueta, y la UI lo dice.
 */
export const LIVE_STOCKS_ES: LiveQuoteSpec[] = [
    { symbol: 'BBVA.MC', name: 'BBVA', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'SAN.MC', name: 'Banco Santander', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'IBE.MC', name: 'Iberdrola', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'ITX.MC', name: 'Inditex', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'REP.MC', name: 'Repsol', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'IDR.MC', name: 'Indra', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'TEF.MC', name: 'Telefónica', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'CABK.MC', name: 'CaixaBank', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'AMS.MC', name: 'Amadeus', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'AENA.MC', name: 'Aena', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'ELE.MC', name: 'Endesa', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
    { symbol: 'FER.MC', name: 'Ferrovial', kind: 'accion', unit: 'EUR', unitLabel: 'EUR/acción' },
];

export const LIVE_COMMODITIES: LiveQuoteSpec[] = [
    { symbol: 'GC=F', name: 'Oro', kind: 'materia', unit: 'USD', unitLabel: 'USD/onza troy' },
    { symbol: 'SI=F', name: 'Plata', kind: 'materia', unit: 'USD', unitLabel: 'USD/onza troy' },
    { symbol: 'HG=F', name: 'Cobre', kind: 'materia', unit: 'USD', unitLabel: 'USD/libra' },
    { symbol: 'CL=F', name: 'Petróleo WTI', kind: 'materia', unit: 'USD', unitLabel: 'USD/barril' },
    { symbol: 'BZ=F', name: 'Petróleo Brent', kind: 'materia', unit: 'USD', unitLabel: 'USD/barril' },
    { symbol: 'NG=F', name: 'Gas natural', kind: 'materia', unit: 'USD', unitLabel: 'USD/MMBtu' },
];

export const LIVE_FX: LiveQuoteSpec[] = [
    { symbol: 'EURUSD=X', name: 'EUR/USD', kind: 'divisa', unit: 'cruz', unitLabel: 'cruz de divisas' },
    { symbol: 'EURGBP=X', name: 'EUR/GBP', kind: 'divisa', unit: 'cruz', unitLabel: 'cruz de divisas' },
    { symbol: 'GBPUSD=X', name: 'GBP/USD', kind: 'divisa', unit: 'cruz', unitLabel: 'cruz de divisas' },
    { symbol: 'USDJPY=X', name: 'USD/JPY', kind: 'divisa', unit: 'cruz', unitLabel: 'cruz de divisas' },
    { symbol: 'EURJPY=X', name: 'EUR/JPY', kind: 'divisa', unit: 'cruz', unitLabel: 'cruz de divisas' },
];

export const LIVE_QUOTE_GROUPS: { key: LiveQuoteKind; specs: LiveQuoteSpec[] }[] = [
    { key: 'indice', specs: LIVE_INDICES },
    { key: 'futuro', specs: LIVE_FUTURES },
    { key: 'accion', specs: LIVE_STOCKS_ES },
    { key: 'materia', specs: LIVE_COMMODITIES },
    { key: 'divisa', specs: LIVE_FX },
];

export interface LiveMarketsResult {
    /** Epoch ms en que se pidieron los datos a Yahoo. */
    fetchedAt: number;
    /** Por grupo, una entrada por simbolo del catalogo (null = Yahoo fallo: N/D). */
    groups: { key: LiveQuoteKind; quotes: (LiveQuote | null)[] }[];
}
