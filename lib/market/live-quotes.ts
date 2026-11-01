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
 * - Los decimales los fija el CATALOGO por instrumento (decimals): un cruz
 *   EUR/USD con 2 decimales pinta "1,12" y cambios "+0,00", precision
 *   insuficiente para FX (21-oct-2026).
 * - Cada cotizacion lleva el timestamp del proveedor; la UI muestra esa hora
 *   (Madrid) y la ANTIGÜEDAD calculada por fila. Nada se etiqueta como
 *   "tiempo real" ni se afirma un retraso generico sin medirlo.
 * - Pre/post mercado: si el proveedor informa preMarketPrice/postMarketPrice
 *   mas reciente que regularMarketTime, se muestra ESE precio con etiqueta
 *   de sesion ("premercado"/"postmercado"); nunca se presenta como precio
 *   de sesion regular.
 * - Identidad del instrumento: simbolo del proveedor + mercado
 *   (exchangeName) + tipo (instrumentType) vienen del meta del proveedor en
 *   la MISMA respuesta ya solicitada; si faltan, se omiten (no se derivan
 *   de la etiqueta visible).
 *
 * Modulo PURO: sin imports de servidor, para probarlo con node --test.
 */

export type LiveQuoteKind = 'indice' | 'futuro' | 'accion' | 'materia' | 'divisa';

/** 'index' = puntos de indice (sin unidad monetaria); el resto son divisas ISO. */
export type LiveQuoteUnit = 'index' | 'EUR' | 'USD' | 'cruz';

/** Sesion a la que pertenece el precio mostrado, segun horas del proveedor. */
export type LiveQuoteSession = 'regular' | 'pre' | 'post';

export interface LiveQuoteSpec {
    /** Simbolo tal cual lo espera la chart API de Yahoo. */
    symbol: string;
    /** Nombre visible en espanol. */
    name: string;
    kind: LiveQuoteKind;
    unit: LiveQuoteUnit;
    /** Decimales del precio y del cambio para ESTE instrumento. */
    decimals: number;
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
    session: LiveQuoteSession;
    /** Mercado que informa Yahoo (p.ej. 'CME', 'BME'); null si no viene. */
    exchangeName: string | null;
    /** Tipo de instrumento que informa Yahoo (p.ej. 'FUTURE'); null si no viene. */
    instrumentType: string | null;
}

/** Meta de la chart API de Yahoo: solo los campos que leemos. */
export interface YahooChartMeta {
    regularMarketPrice?: number | null;
    regularMarketTime?: number | null;
    preMarketPrice?: number | null;
    preMarketTime?: number | null;
    postMarketPrice?: number | null;
    postMarketTime?: number | null;
    currency?: string | null;
    exchangeName?: string | null;
    fullExchangeName?: string | null;
    instrumentType?: string | null;
    /** Zona horaria del mercado (p.ej. 'America/New_York'); necesaria para el cierre de referencia. */
    exchangeTimezoneName?: string | null;
}

/** Barras diarias del MISMO response de la chart API (range=2d&interval=1d). */
export interface YahooBars {
    timestamps?: (number | null)[] | null;
    closes?: (number | null)[] | null;
}

const isFiniteNumber = (value: unknown): value is number =>
    typeof value === 'number' && Number.isFinite(value);

/**
 * Convierte el meta de Yahoo en una LiveQuote, o null si no hay precio
 * utilizable (la UI pinta N/D para ese valor, nunca un 0 inventado).
 * Se elige el precio de la sesion mas reciente segun las horas del
 * proveedor; a igualdad de hora (o sin hora) gana la sesion regular.
 */
export function parseYahooQuote(spec: LiveQuoteSpec, meta: YahooChartMeta | null | undefined, bars?: YahooBars | null): LiveQuote | null {
    if (!meta) return null;
    const candidates: { price: number; time: number | null; session: LiveQuoteSession; prio: number }[] = [];
    if (isFiniteNumber(meta.regularMarketPrice) && meta.regularMarketPrice > 0) {
        candidates.push({
            price: meta.regularMarketPrice,
            time: isFiniteNumber(meta.regularMarketTime) ? meta.regularMarketTime : null,
            session: 'regular',
            prio: 0,
        });
    }
    if (isFiniteNumber(meta.postMarketPrice) && meta.postMarketPrice > 0) {
        candidates.push({
            price: meta.postMarketPrice,
            time: isFiniteNumber(meta.postMarketTime) ? meta.postMarketTime : null,
            session: 'post',
            prio: 1,
        });
    }
    if (isFiniteNumber(meta.preMarketPrice) && meta.preMarketPrice > 0) {
        candidates.push({
            price: meta.preMarketPrice,
            time: isFiniteNumber(meta.preMarketTime) ? meta.preMarketTime : null,
            session: 'pre',
            prio: 2,
        });
    }
    if (candidates.length === 0) return null;
    candidates.sort((a, b) => (b.time ?? -Infinity) - (a.time ?? -Infinity) || a.prio - b.prio);
    const best = candidates[0];
    // Cierre de referencia SOLO desde barras diarias reales del proveedor:
    // previousClose/chartPreviousClose del meta son poco fiables (21-oct-2026,
    // ^GSPC: chartPreviousClose 7690,73 vs cierre real del dia anterior
    // 7712,57). Sin referencia demostrable => cambio N/D, nunca inventado.
    const timezone = typeof meta.exchangeTimezoneName === 'string' && meta.exchangeTimezoneName.trim()
        ? meta.exchangeTimezoneName.trim()
        : null;
    const prevClose = best.session === 'post'
        ? postReferenceCloseFromBars(bars, best.time, timezone)
        : referenceCloseFromBars(bars, best.time, timezone);
    const change = prevClose === null ? null : best.price - prevClose;
    const changePercent = prevClose === null ? null : (best.price - prevClose) / prevClose * 100;
    return {
        ...spec,
        price: best.price,
        change,
        changePercent,
        timestamp: best.time,
        currency: typeof meta.currency === 'string' ? meta.currency : null,
        session: best.session,
        exchangeName: typeof meta.exchangeName === 'string' && meta.exchangeName.trim() ? meta.exchangeName.trim()
            : typeof meta.fullExchangeName === 'string' && meta.fullExchangeName.trim() ? meta.fullExchangeName.trim()
            : null,
        instrumentType: typeof meta.instrumentType === 'string' && meta.instrumentType.trim() ? meta.instrumentType.trim() : null,
    };
}

/** Dia civil ('YYYY-MM-DD') de un epoch en la zona horaria del mercado; null si la tz no es valida. */
function marketDayKey(epochSec: number, tz: string): string | null {
    try {
        return new Intl.DateTimeFormat('en-CA', {
            timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
        }).format(new Date(epochSec * 1000));
    } catch {
        return null;
    }
}

/**
 * Cierre de referencia para el cambio, por dia de sesion y en la zona del
 * mercado, usando SOLO barras diarias reales:
 * - la cotizacion es de un dia CON barra (sesion en curso o cerrada): la
 *   referencia es el cierre de la barra anterior; si no hay barra anterior
 *   (una sola barra) no hay referencia demostrable => null (N/D);
 * - la cotizacion es de un dia SIN barra (premercado, finde, festivo): la
 *   referencia es el cierre de la ultima barra existente;
 * - barras vacias, cierres null, hora de cotizacion ausente o zona horaria
 *   desconocida => null (N/D), nunca un dato inventado.
 */
function validDailyBars(bars: YahooBars | null | undefined): { t: number; c: number }[] {
    if (!bars) return [];
    const ts = Array.isArray(bars.timestamps) ? bars.timestamps : [];
    const cl = Array.isArray(bars.closes) ? bars.closes : [];
    const valid: { t: number; c: number }[] = [];
    for (let i = 0; i < Math.min(ts.length, cl.length); i++) {
        const t = ts[i];
        const c = cl[i];
        if (isFiniteNumber(t) && isFiniteNumber(c) && c > 0) valid.push({ t, c });
    }
    return valid;
}

export function referenceCloseFromBars(
    bars: YahooBars | null | undefined,
    quoteTimeSec: number | null,
    exchangeTimezone: string | null,
): number | null {
    if (quoteTimeSec === null || !exchangeTimezone) return null;
    const valid = validDailyBars(bars);
    if (valid.length === 0) return null;
    const quoteDay = marketDayKey(quoteTimeSec, exchangeTimezone);
    const lastDay = marketDayKey(valid[valid.length - 1].t, exchangeTimezone);
    if (quoteDay === null || lastDay === null) return null;
    if (quoteDay === lastDay) {
        return valid.length >= 2 ? valid[valid.length - 2].c : null;
    }
    return valid[valid.length - 1].c;
}

/**
 * Referencia para una cotizacion de POSTMERCADO: el cierre regular de HOY,
 * probado por una barra diaria de hoy con cierre valido. Sin barra de hoy
 * no hay referencia demostrable => null (N/D); NUNCA se cae al cierre de
 * ayer, que pintaria el movimiento de dos sesiones como si fuera el del
 * postmercado (reserva del auditor, 21-oct-2026).
 */
export function postReferenceCloseFromBars(
    bars: YahooBars | null | undefined,
    quoteTimeSec: number | null,
    exchangeTimezone: string | null,
): number | null {
    if (quoteTimeSec === null || !exchangeTimezone) return null;
    const valid = validDailyBars(bars);
    if (valid.length === 0) return null;
    const quoteDay = marketDayKey(quoteTimeSec, exchangeTimezone);
    const lastDay = marketDayKey(valid[valid.length - 1].t, exchangeTimezone);
    if (quoteDay === null || lastDay === null || quoteDay !== lastDay) return null;
    return valid[valid.length - 1].c;
}

/** Antiguedad de una cotizacion en segundos; nunca negativa (desfase de reloj => 0). */
export function quoteAgeSeconds(fetchedAtMs: number, timestampSec: number | null): number | null {
    if (timestampSec === null) return null;
    return Math.max(0, Math.round(fetchedAtMs / 1000 - timestampSec));
}

/**
 * Antiguedad legible y explicita, sin aproximacion implicita:
 * - <60 s: exacta ("hace 40 s");
 * - <60 min: redondeada y MARCADA como aproximada ("hace ~3 min");
 * - >=60 min: horas y minutos exactos a suelo ("hace 1 h 59 min"),
 *   porque el suelo de horas solo subestimaba en la unidad oculta.
 * Valores NO finitos => "N/D": frescura desconocida, nunca disfrazada de 0 s.
 * Cero o futuros (desfase de reloj; clamp preexistente de quoteAgeSeconds)
 * => "hace 0 s" (comportamiento anterior, registrado, sin ampliar).
 */
export function formatQuoteAge(ageSeconds: number, locale: 'es' | 'en' = 'es'): string {
    if (locale === 'en') return formatQuoteAgeEn(ageSeconds);
    if (!Number.isFinite(ageSeconds)) return 'N/D';
    if (ageSeconds <= 0) return 'hace 0 s';
    if (ageSeconds < 60) return `hace ${Math.floor(ageSeconds)} s`;
    if (ageSeconds < 3600) {
        const m = Math.round(ageSeconds / 60);
        return m >= 60 ? 'hace 1 h' : `hace ~${m} min`;
    }
    const h = Math.floor(ageSeconds / 3600);
    const m = Math.floor((ageSeconds % 3600) / 60);
    return m === 0 ? `hace ${h} h` : `hace ${h} h ${m} min`;
}

/** Misma escala que formatQuoteAge, en inglés (Ajustes → Idioma). */
function formatQuoteAgeEn(ageSeconds: number): string {
    if (!Number.isFinite(ageSeconds)) return 'N/A';
    if (ageSeconds <= 0) return '0 s ago';
    if (ageSeconds < 60) return `${Math.floor(ageSeconds)} s ago`;
    if (ageSeconds < 3600) {
        const m = Math.round(ageSeconds / 60);
        return m >= 60 ? '1 h ago' : `~${m} min ago`;
    }
    const h = Math.floor(ageSeconds / 3600);
    const m = Math.floor((ageSeconds % 3600) / 60);
    return m === 0 ? `${h} h ago` : `${h} h ${m} min ago`;
}

const numberFormat = (decimals: number, sign: boolean, locale: 'es' | 'en' = 'es') =>
    new Intl.NumberFormat(locale === 'en' ? 'en-US' : 'es-ES', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
        signDisplay: sign ? 'always' : 'auto',
    });

const ZERO_PATTERN = /^[+-]?0[,.]0+$/;

/**
 * Cambio con los decimales del instrumento. Si con esos decimales redondea
 * a cero pero NO es cero ("-0,00" engañoso), amplia a decimals+2 para que
 * el signo y la magnitud sean reales.
 */
export function formatQuoteChange(value: number, decimals: number, locale: 'es' | 'en' = 'es'): string {
    const formatted = numberFormat(decimals, true, locale).format(value);
    if (value !== 0 && ZERO_PATTERN.test(formatted)) {
        return numberFormat(Math.min(decimals + 2, 8), true, locale).format(value);
    }
    return formatted;
}

/**
 * Porcentaje de cambio con 2 decimales. Misma regla anti-cero que
 * formatQuoteChange: si redondea a "+0,00%" sin ser cero, amplia a 4
 * decimales para que signo y magnitud sean reales (un cruce moviendose
 * un pip no es "no moverse").
 */
export function formatQuoteChangePercent(value: number, locale: 'es' | 'en' = 'es'): string {
    const formatted = numberFormat(2, true, locale).format(value);
    if (value !== 0 && ZERO_PATTERN.test(formatted)) {
        return numberFormat(4, true, locale).format(value);
    }
    return formatted;
}

/** Tipo de instrumento localizado; null si Yahoo informa uno desconocido (no se inventa). */
export function localizeInstrumentType(instrumentType: string | null, locale: 'es' | 'en' = 'es'): string | null {
    if (locale === 'en') {
        switch (instrumentType) {
            case 'FUTURE': return 'future';
            case 'EQUITY': return 'stock';
            case 'INDEX': return 'index';
            case 'CURRENCY': return 'currency';
            case 'ETF': return 'ETF';
            default: return null;
        }
    }
    switch (instrumentType) {
        case 'FUTURE': return 'futuro';
        case 'EQUITY': return 'acción';
        case 'INDEX': return 'índice';
        case 'CURRENCY': return 'divisa';
        case 'ETF': return 'ETF';
        default: return null;
    }
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
 * Decimales por instrumento (21-oct-2026): cruces sin JPY a 4 (un pip),
 * cruces con JPY a 3; resto a 2.
 * ------------------------------------------------------------------ */

export const LIVE_INDICES: LiveQuoteSpec[] = [
    { symbol: '^GSPC', name: 'S&P 500', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^IXIC', name: 'Nasdaq Composite', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^DJI', name: 'Dow Jones', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^RUT', name: 'Russell 2000', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^IBEX', name: 'IBEX 35', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^STOXX50E', name: 'Euro Stoxx 50', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^GDAXI', name: 'DAX', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^FTSE', name: 'FTSE 100', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^FCHI', name: 'CAC 40', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^N225', name: 'Nikkei 225', kind: 'indice', unit: 'index', decimals: 2 },
    { symbol: '^VIX', name: 'VIX (volatilidad S&P 500)', kind: 'indice', unit: 'index', decimals: 2 },
];

export const LIVE_FUTURES: LiveQuoteSpec[] = [
    { symbol: 'ES=F', name: 'Futuro S&P 500 (E-mini)', kind: 'futuro', unit: 'index', decimals: 2 },
    { symbol: 'NQ=F', name: 'Futuro Nasdaq 100 (E-mini)', kind: 'futuro', unit: 'index', decimals: 2 },
    { symbol: 'YM=F', name: 'Futuro Dow Jones (mini)', kind: 'futuro', unit: 'index', decimals: 2 },
    { symbol: 'RTY=F', name: 'Futuro Russell 2000 (E-mini)', kind: 'futuro', unit: 'index', decimals: 2 },
];

/**
 * Seleccion fija de valores liquidos del IBEX 35. NO es un ranking por
 * volumen: sin una fuente gratuita de "mas negociadas" no se puede
 * sostener esa etiqueta, y la UI lo dice.
 */
export const LIVE_STOCKS_ES: LiveQuoteSpec[] = [
    { symbol: 'BBVA.MC', name: 'BBVA', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'SAN.MC', name: 'Banco Santander', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'IBE.MC', name: 'Iberdrola', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'ITX.MC', name: 'Inditex', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'REP.MC', name: 'Repsol', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'IDR.MC', name: 'Indra', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'TEF.MC', name: 'Telefónica', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'CABK.MC', name: 'CaixaBank', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'AMS.MC', name: 'Amadeus', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'AENA.MC', name: 'Aena', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'ELE.MC', name: 'Endesa', kind: 'accion', unit: 'EUR', decimals: 2 },
    { symbol: 'FER.MC', name: 'Ferrovial', kind: 'accion', unit: 'EUR', decimals: 2 },
];

export const LIVE_COMMODITIES: LiveQuoteSpec[] = [
    { symbol: 'GC=F', name: 'Oro', kind: 'materia', unit: 'USD', decimals: 2 },
    { symbol: 'SI=F', name: 'Plata', kind: 'materia', unit: 'USD', decimals: 2 },
    { symbol: 'HG=F', name: 'Cobre', kind: 'materia', unit: 'USD', decimals: 3 },
    { symbol: 'CL=F', name: 'Petróleo WTI', kind: 'materia', unit: 'USD', decimals: 2 },
    { symbol: 'BZ=F', name: 'Petróleo Brent', kind: 'materia', unit: 'USD', decimals: 2 },
    { symbol: 'NG=F', name: 'Gas natural', kind: 'materia', unit: 'USD', decimals: 3 },
];

export const LIVE_FX: LiveQuoteSpec[] = [
    { symbol: 'EURUSD=X', name: 'EUR/USD', kind: 'divisa', unit: 'cruz', decimals: 4 },
    { symbol: 'EURGBP=X', name: 'EUR/GBP', kind: 'divisa', unit: 'cruz', decimals: 4 },
    { symbol: 'GBPUSD=X', name: 'GBP/USD', kind: 'divisa', unit: 'cruz', decimals: 4 },
    { symbol: 'USDJPY=X', name: 'USD/JPY', kind: 'divisa', unit: 'cruz', decimals: 3 },
    { symbol: 'EURJPY=X', name: 'EUR/JPY', kind: 'divisa', unit: 'cruz', decimals: 3 },
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

/** Fila del panel: la identidad del instrumento siempre presente, cotice o no. */
export interface LiveQuoteRow {
    spec: LiveQuoteSpec;
    quote: LiveQuote | null;
}

/**
 * Empareja las cotizaciones de un grupo con las specs del catalogo de forma
 * ROBUSTA: por simbolo cuando la cotizacion existe (autosana cualquier
 * reordenacion del array) y por posicion cuando el proveedor fallo (null).
 * Devuelve las filas en el orden del catalogo, de modo que una fila N/D
 * nunca sea anonima: la UI siempre puede pintar nombre y simbolo.
 */
export function resolveGroupRows(groupKey: LiveQuoteKind, quotes: (LiveQuote | null)[] | null | undefined): LiveQuoteRow[] {
    const specs = LIVE_QUOTE_GROUPS.find((g) => g.key === groupKey)?.specs ?? [];
    return specs.map((spec, i) => {
        const positional = quotes?.[i] ?? null;
        if (positional && positional.symbol === spec.symbol) return { spec, quote: positional };
        const bySymbol = quotes?.find((q) => q !== null && q.symbol === spec.symbol) ?? null;
        return { spec, quote: bySymbol };
    });
}
