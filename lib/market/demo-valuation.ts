/**
 * Valoracion de las posiciones de la cuenta demo MANUAL con cotizaciones
 * REALES ya saneadas (SanitizedQuote de lib/market/quote-freshness).
 *
 * Modulo PURO (sin servidor, sin red, sin reloj): testeable con node --test.
 *
 * Reglas de honestidad (todas cubiertas por scripts/demo-valuation.test.ts):
 * - Precio de entrada UNICO: la cotizacion de Finnhub (/quote directo,
 *   frescura validada). NUNCA se usa el precio del ultimo fill como precio
 *   de mercado. Sin cotizacion => N/D, no un valor imputado.
 * - Cada fila lleva su etiqueta: proveedor + hora de la cotizacion ("en
 *   vivo") o fecha del cierre.
 * - Fuente aprobada: Finnhub (/quote directo, frescura validada) para los
 *   símbolos del listado US, o la cotización del BACKEND propio (Yahoo chart
 *   API saneada en data-engine, con la divisa declarada por el backend) para
 *   los mercados que Finnhub free no cubre (.MC, .PA, .DE...). Una cotización
 *   de cualquier otra fuente — o una del backend SIN divisa declarada — sale
 *   N/D y no cuenta como valorada.
 * - Divisa: NUNCA se infiere del simbolo ni del sufijo. La divisa debe venir
 *   en ValuationQuote.currency, que la accion rellena SOLO con la divisa de
 *   cotizacion del listado US de Finnhub (/stock/symbol?exchange=US, campo
 *   currency) o con la divisa declarada por el backend (meta.currency de
 *   Yahoo, copiada tal cual por data-engine, sin normalizar). Solo 'EUR' y
 *   'USD' exactos se
 *   valoran. Sin divisa verificada => N/D. Si no coincide con la divisa de
 *   la posicion => N/D (sin conversion).
 * - Opciones: la cotizacion del subyacente NO es la prima del contrato.
 *   Se valoran SOLO con la prima real del contrato: la ultima operacion
 *   publicada por la delayed quotes API de CBOE (lib/market/cboe-options.ts,
 *   dato diferido, etiquetado con su hora de Nueva York). Sin cadena
 *   consultable, contrato no encontrado o contrato sin operacion registrada
 *   => N/D con el motivo: NUNCA se inventa una prima (ni bid/ask, ni el
 *   precio del ultimo fill). Las primas de CBOE son USD (propiedad de la
 *   fuente): una opcion en otra divisa sale N/D sin conversion.
 * - Los totales suman SOLO las posiciones valoradas, por divisa, y se
 *   acompanan de la cobertura "N de M".
 */

// @ts-expect-error TS5097
import { DEFAULT_LOCALE, type Locale } from '../i18n/locale.ts';
// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';
// @ts-expect-error TS5097
import { parseOptionKey } from '../paper-trading/types.ts';

export type ValuationCurrency = 'EUR' | 'USD';

export type ValuationPosition = {
    instrumentKey: string;
    name: string;
    kind: 'accion' | 'opcion';
    currency: ValuationCurrency;
    quantity: number;
    avgCost: number;
};

/** Subconjunto de SanitizedQuote que consume la valoracion. */
export type ValuationQuote = {
    source?: 'Finnhub' | 'Yahoo Finance';
    /** Divisa de cotizacion verificada en el listado de Finnhub; ausente/null si no se pudo verificar. */
    currency?: string | null;
    c: number;
    /** Epoch en segundos del proveedor; null en Yahoo (sin hora). */
    t: number | null;
    closeDate?: string | null;
    kind: 'live' | 'close';
};

export type ValuationStatus = 'valorada' | 'sin-cotizacion' | 'no-consultada' | 'fuente-no-aprobada' | 'divisa-no-coincide' | 'opcion-no-valorada';

export type ValuedPosition = {
    instrumentKey: string;
    name: string;
    kind: 'accion' | 'opcion';
    currency: ValuationCurrency;
    quantity: number;
    status: ValuationStatus;
    /** Precio de mercado por unidad; null si no hay valoracion. */
    price: number | null;
    marketValue: number | null;
    unrealizedPnl: number | null;
    /** PyG no realizada sobre el coste; null sin valoracion o con coste 0. */
    unrealizedPct: number | null;
    /** Coste medio por unidad con el que se valoro (para detectar valoracion caducada). */
    avgCost: number;
    /** Origen de la divisa de la cotizacion; null si no hay valoracion. */
    currencyBasis: 'finnhub-listado' | 'backend-yahoo' | 'cboe' | null;
    /** Etiqueta de fuente/hora por fila; null si no hay cotizacion. */
    quoteLabel: string | null;
    /** Motivo legible cuando no esta valorada. */
    note: string | null;
};

export type ValuationTotal = {
    currency: ValuationCurrency;
    marketValue: number;
    unrealizedPnl: number;
    costBasis: number;
    valuedPositions: number;
};

export type DemoValuation = {
    rows: ValuedPosition[];
    totals: ValuationTotal[];
    coverage: { valued: number; total: number };
};

/** Simbolo de la clave de instrumento ('A:ASTS' -> 'ASTS'); null si no es accion. */
export function symbolFromKey(instrumentKey: string): string | null {
    return instrumentKey.startsWith('A:') && instrumentKey.length > 2 ? instrumentKey.slice(2) : null;
}

export type QuoteCurrency = { currency: ValuationCurrency | null; basis: 'finnhub-listado' | 'backend-yahoo' | null; reason: string | null };

/** Divisa de la cotizacion SOLO si viene declarada por la fuente admitida (listado US de Finnhub o backend propio); nunca por sufijo ni por ausencia de ella. */
export function resolveQuoteCurrency(quote: ValuationQuote, locale: Locale = DEFAULT_LOCALE): QuoteCurrency {
    const declared = typeof quote.currency === 'string' ? quote.currency.trim() : '';
    const basis = quote.source === 'Yahoo Finance' ? 'backend-yahoo' : 'finnhub-listado';
    if (declared === 'EUR' || declared === 'USD') return { currency: declared, basis, reason: null };
    const t = createTranslator(locale);
    if (declared) {
        const key = quote.source === 'Yahoo Finance' ? 'paperTrading.valuation.rowNotes.backendCurrency' : 'paperTrading.valuation.rowNotes.listingCurrency';
        return { currency: null, basis: null, reason: t(key, { currency: declared }) };
    }
    const key = quote.source === 'Yahoo Finance' ? 'paperTrading.valuation.rowNotes.currencyNotVerifiedBackend' : 'paperTrading.valuation.rowNotes.currencyNotVerifiedListing';
    return { currency: null, basis: null, reason: t(key) };
}

/** Prima real de un contrato de opcion (CBOE saneada en lib/market/cboe-options.ts). */
export type OptionPremiumQuote = {
    /** Ultimo precio negociado (prima por accion); null si nunca negocio. */
    lastTradePrice: number | null;
    /** Hora de la ultima operacion "yyyy-mm-ddThh:mm:ss" (Nueva York, naive); null sin operacion. */
    lastTradeTime: string | null;
};

/**
 * Resultado de consultar la prima de UN contrato (clave = instrumentKey):
 * - undefined: ni se intento (camino antiguo/sin consulta) => 'opcion-no-valorada'.
 * - { fetchFailed: true }: la fuente fallo o no cubre el subyacente => 'sin-cotizacion'.
 * - { quote: null }: cadena consultada y el contrato NO esta (vencido, ajustado, inexistente).
 * - { quote }: cadena consultada y contrato encontrado (puede no tener operacion: N/D honesto).
 */
export type OptionPremiumLookup = { quote: OptionPremiumQuote | null; fetchFailed: boolean } | undefined;

/** Mapa simbolo -> divisa del listado US de Finnhub (/stock/symbol); ignora entradas sin simbolo o divisa. */
export function parseListingCurrencies(payload: unknown): Map<string, string> {
    const map = new Map<string, string>();
    if (!Array.isArray(payload)) return map;
    for (const item of payload) {
        const symbol = typeof item?.symbol === 'string' ? item.symbol.trim().toUpperCase() : '';
        const currency = typeof item?.currency === 'string' ? item.currency.trim() : '';
        if (symbol && currency) map.set(symbol, currency);
    }
    return map;
}

const NY_DATE_FORMAT = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });

/** Fecha civil de Nueva York (yyyy-mm-dd) de un instante; null si no es finito. */
export function nyCivilDate(nowMs: number): string | null {
    if (!Number.isFinite(nowMs)) return null;
    const parts = NY_DATE_FORMAT.formatToParts(new Date(nowMs));
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    const date = `${get('year')}-${get('month')}-${get('day')}`;
    return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null;
}

const CIVIL_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_BUSINESS_DAY_SPAN = 3_700; // ~10 años: tope defensivo del bucle.

/**
 * Días hábiles (lunes-viernes) transcurridos desde la fecha civil de la
 * última operación hasta la de referencia, AMBAS en Nueva York: el mismo
 * día cuenta 0; del viernes al lunes cuenta 1. Los festivos de mercado no
 * se conocen sin calendario oficial, así que no se descuentan (el aviso de
 * prima envejecida puede llegar algo más tarde tras un festivo: se documenta
 * y no se inventa). null si alguna fecha no es civil válida.
 */
export function businessDaysSinceTrade(tradeDate: string, referenceDate: string): number | null {
    if (!CIVIL_DATE_RE.test(tradeDate) || !CIVIL_DATE_RE.test(referenceDate)) return null;
    const from = Date.parse(`${tradeDate}T00:00:00Z`);
    const to = Date.parse(`${referenceDate}T00:00:00Z`);
    if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return null;
    let days = 0;
    for (let ms = from + 86_400_000; ms <= to && days <= MAX_BUSINESS_DAY_SPAN; ms += 86_400_000) {
        const dow = new Date(ms).getUTCDay();
        if (dow !== 0 && dow !== 6) days += 1;
    }
    return days;
}

/** Más de 1 día hábil desde la última operación => prima envejecida (aviso visible). */
export const STALE_PREMIUM_BUSINESS_DAYS = 1;

const TIME_FORMATS = {
    es: new Intl.DateTimeFormat('es-ES', { timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }),
    en: new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }),
} as const;
const DATE_FORMATS = {
    es: new Intl.DateTimeFormat('es-ES', { timeZone: 'Europe/Madrid', day: 'numeric', month: 'short' }),
    en: new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Madrid', day: 'numeric', month: 'short' }),
} as const;

function formatsFor(locale: Locale) {
    return locale === 'en' ? { time: TIME_FORMATS.en, date: DATE_FORMATS.en } : { time: TIME_FORMATS.es, date: DATE_FORMATS.es };
}

function shortDate(d: Date, locale: Locale): string {
    return formatsFor(locale).date.format(d).replace('.', '');
}

/** Etiqueta honesta de hora/fecha de una cotizacion, sin nombrar la fuente. */
export function quoteLabel(quote: ValuationQuote, locale: Locale = DEFAULT_LOCALE): string {
    // Etiqueta de calidad sin nombrar la fuente (orden de Nico, 31-oct): la
    // procedencia sigue en la pestana Fuentes y en la API.
    const t = createTranslator(locale);
    const { time } = formatsFor(locale);
    if (quote.kind === 'live' && typeof quote.t === 'number' && quote.t > 0) {
        return t('paperTrading.valuation.quoteLabels.live', { time: time.format(new Date(quote.t * 1000)) });
    }
    if (quote.closeDate) return t('paperTrading.valuation.quoteLabels.close', { date: shortDate(new Date(`${quote.closeDate}T12:00:00Z`), locale) });
    if (typeof quote.t === 'number' && quote.t > 0) {
        const d = new Date(quote.t * 1000);
        return t('paperTrading.valuation.quoteLabels.lastClose', { date: shortDate(d, locale), time: time.format(d) });
    }
    return t('paperTrading.valuation.quoteLabels.unknownClose');
}

function unvalued(position: ValuationPosition, status: ValuationStatus, note: string, label: string | null = null): ValuedPosition {
    return {
        instrumentKey: position.instrumentKey,
        name: position.name,
        kind: position.kind,
        currency: position.currency,
        quantity: position.quantity,
        status,
        price: null,
        marketValue: null,
        unrealizedPnl: null,
        unrealizedPct: null,
        avgCost: position.avgCost,
        currencyBasis: null,
        quoteLabel: label,
        note,
    };
}

const cents = (n: number): number => Math.round(n * 100) / 100;

/** Etiqueta de la ultima operacion de una opcion: fecha civil + hora TAL CUAL las publica la fuente (Nueva York), sin conversion. */
export function optionQuoteLabel(lastTradeTime: string, locale: Locale = DEFAULT_LOCALE): string {
    const t = createTranslator(locale);
    const [datePart, timePartRaw] = lastTradeTime.split('T');
    const date = /^\d{4}-\d{2}-\d{2}$/.test(datePart ?? '') ? shortDate(new Date(`${datePart}T12:00:00Z`), locale) : (datePart ?? '');
    const time = (timePartRaw ?? '').slice(0, 5);
    return t('paperTrading.valuation.quoteLabels.optionLastTrade', { date, time });
}

/** Multiplicador fase 1 (contrato estandar OCC): igual que lib/paper-trading/options.ts. */
const OPTION_MULTIPLIER = 100;

/**
 * Rama de opciones de valuePositions: valora SOLO con la prima real del
 * contrato; cualquier hueco se queda en N/D con su motivo, nunca con la
 * cotizacion del subyacente ni con el precio del ultimo fill.
 */
function valueOptionPosition(
    position: ValuationPosition,
    lookup: OptionPremiumLookup,
    optionsNotQueried: ReadonlySet<string> | undefined,
    optionUnderlyingLimit: number,
    t: ReturnType<typeof createTranslator>,
    locale: Locale,
    optionPremiumNowMs: number | undefined,
): ValuedPosition {
    // Las primas de la delayed quotes API de CBOE son USD (propiedad de la
    // fuente, no inferida del simbolo): otra divisa => N/D sin conversion.
    if (position.currency !== 'USD') {
        return unvalued(position, 'divisa-no-coincide', t('paperTrading.valuation.rowNotes.currencyMismatch', { quote: 'USD', position: position.currency }));
    }
    const parsed = parseOptionKey(position.instrumentKey);
    if (!parsed) return unvalued(position, 'sin-cotizacion', t('paperTrading.valuation.rowNotes.noSymbol'));
    if (optionsNotQueried?.has(parsed.underlying.toUpperCase())) {
        return unvalued(position, 'no-consultada', t('paperTrading.valuation.rowNotes.optionNotQueried', { limit: optionUnderlyingLimit }));
    }
    if (lookup === undefined) {
        // Ni se intento consultar la prima (camino sin consulta): la regla
        // historica de la demo es no valerse del subyacente.
        return unvalued(position, 'opcion-no-valorada', t('paperTrading.valuation.rowNotes.optionNotValued'));
    }
    if (lookup.fetchFailed) {
        return unvalued(position, 'sin-cotizacion', t('paperTrading.valuation.rowNotes.optionNoQuote'));
    }
    if (lookup.quote === null) {
        return unvalued(position, 'sin-cotizacion', t('paperTrading.valuation.rowNotes.optionContractNotFound'));
    }
    const { lastTradePrice, lastTradeTime } = lookup.quote;
    if (lastTradePrice === null || !Number.isFinite(lastTradePrice) || lastTradePrice < 0) {
        return unvalued(position, 'sin-cotizacion', t('paperTrading.valuation.rowNotes.optionNoTrades'));
    }
    if (lastTradeTime === null) {
        // Precio SIN hora: la etiqueta "diferida" necesita la hora real de la
        // operación, así que la fila es N/D con su motivo propio (no es "sin
        // operación registrada": hay precio).
        return unvalued(position, 'sin-cotizacion', t('paperTrading.valuation.rowNotes.optionNoTradeTime'));
    }
    const marketValue = cents(position.quantity * lastTradePrice * OPTION_MULTIPLIER);
    const cost = position.quantity * position.avgCost * OPTION_MULTIPLIER;
    const pnl = cents(marketValue - cost);
    // Prima envejecida: la última operación del contrato tiene más de 1 día
    // hábil (civil de Nueva York, sin calendario de festivos). La fila SIGUE
    // valorada (el dato es real) pero el aviso es visible, nunca escondido:
    // una cadena poco líquida puede mezclar operaciones de días distintos.
    let note: string | null = null;
    if (optionPremiumNowMs !== undefined) {
        const referenceDate = nyCivilDate(optionPremiumNowMs);
        const elapsed = referenceDate === null ? null : businessDaysSinceTrade(lastTradeTime.slice(0, 10), referenceDate);
        if (elapsed !== null && elapsed > STALE_PREMIUM_BUSINESS_DAYS) {
            note = t('paperTrading.valuation.rowNotes.optionStalePremium');
        }
    }
    return {
        instrumentKey: position.instrumentKey,
        name: position.name,
        kind: 'opcion',
        currency: position.currency,
        quantity: position.quantity,
        status: 'valorada',
        price: lastTradePrice,
        marketValue,
        unrealizedPnl: pnl,
        unrealizedPct: cost > 0 ? (pnl / cost) * 100 : null,
        avgCost: position.avgCost,
        currencyBasis: 'cboe',
        quoteLabel: optionQuoteLabel(lastTradeTime, locale),
        note,
    };
}

/**
 * Valora cada posicion con `quotes` (clave = simbolo en mayusculas). Un
 * simbolo ausente del mapa o con null cuenta como "sin cotizacion".
 */
export function valuePositions(
    positions: ValuationPosition[],
    quotes: Record<string, ValuationQuote | null | undefined>,
    options: {
        notQueried?: ReadonlySet<string>;
        currencyUnverified?: ReadonlySet<string>;
        locale?: Locale;
        /** Primas reales por instrumentKey (CBOE); ver OptionPremiumLookup. */
        optionPremiums?: ReadonlyMap<string, OptionPremiumLookup>;
        /** Subyacentes de opcion por ENCIMA del tope por consulta (no se pidieron). */
        optionsNotQueried?: ReadonlySet<string>;
        /** Tope aplicado, para el motivo "limite de N". */
        optionUnderlyingLimit?: number;
        /**
         * Reloj (epoch ms) para el aviso de prima envejecida: sin él no se
         * juzga la frescura de la última operación (camino antiguo/tests).
         */
        optionPremiumNowMs?: number;
    } = {},
): DemoValuation {
    const locale: Locale = options.locale ?? DEFAULT_LOCALE;
    const t = createTranslator(locale);
    const rows: ValuedPosition[] = positions.map((position) => {
        if (position.kind === 'opcion') {
            return valueOptionPosition(
                position,
                options.optionPremiums?.get(position.instrumentKey),
                options.optionsNotQueried,
                options.optionUnderlyingLimit ?? 0,
                t,
                locale,
                options.optionPremiumNowMs,
            );
        }
        const symbol = symbolFromKey(position.instrumentKey);
        if (!symbol) return unvalued(position, 'sin-cotizacion', t('paperTrading.valuation.rowNotes.noSymbol'));
        if (options.notQueried?.has(symbol.toUpperCase())) {
            return unvalued(position, 'no-consultada', t('paperTrading.valuation.rowNotes.notQueried'));
        }
        if (options.currencyUnverified?.has(symbol.toUpperCase())) {
            // No se intento ninguna cotizacion: no hay divisa verificable (listado caido o simbolo ausente).
            return unvalued(position, 'divisa-no-coincide', t('paperTrading.valuation.rowNotes.currencyUnverified'));
        }
        const quote = quotes[symbol.toUpperCase()];
        if (!quote || !Number.isFinite(quote.c) || quote.c <= 0) {
            return unvalued(position, 'sin-cotizacion', t('paperTrading.valuation.rowNotes.noQuote'));
        }
        const label = quoteLabel(quote, locale);
        const declaredCurrency = typeof quote.currency === 'string' && quote.currency.trim() !== '';
        if (quote.source === 'Yahoo Finance' && !declaredCurrency) {
            // Cotizacion del backend SIN divisa declarada: N/D con aviso; la
            // divisa nunca se infiere del simbolo ni del sufijo.
            return unvalued(position, 'divisa-no-coincide', t('paperTrading.valuation.rowNotes.currencyNotVerifiedBackend'), label);
        }
        if (quote.source !== 'Finnhub' && quote.source !== 'Yahoo Finance') {
            return unvalued(
                position,
                'fuente-no-aprobada',
                t('paperTrading.valuation.rowNotes.sourceNotApproved'),
                null,
            );
        }
        const resolved = resolveQuoteCurrency(quote, locale);
        if (resolved.currency === null) {
            return unvalued(position, 'divisa-no-coincide', resolved.reason ?? t('paperTrading.valuation.rowNotes.currencyUnknown'), label);
        }
        if (resolved.currency !== position.currency) {
            return unvalued(
                position,
                'divisa-no-coincide',
                t('paperTrading.valuation.rowNotes.currencyMismatch', { quote: resolved.currency, position: position.currency }),
                label,
            );
        }
        const marketValue = cents(position.quantity * quote.c);
        const cost = position.quantity * position.avgCost;
        const pnl = cents(marketValue - cost);
        return {
            instrumentKey: position.instrumentKey,
            name: position.name,
            kind: position.kind,
            currency: position.currency,
            quantity: position.quantity,
            status: 'valorada',
            price: quote.c,
            marketValue,
            unrealizedPnl: pnl,
            unrealizedPct: cost > 0 ? (pnl / cost) * 100 : null,
            avgCost: position.avgCost,
            currencyBasis: resolved.basis,
            quoteLabel: label,
            note: null,
        };
    });

    const byCurrency = new Map<ValuationCurrency, ValuationTotal>();
    positions.forEach((position, i) => {
        const row = rows[i];
        if (row.status !== 'valorada' || row.marketValue === null || row.unrealizedPnl === null) return;
        const total = byCurrency.get(position.currency) ?? {
            currency: position.currency,
            marketValue: 0,
            unrealizedPnl: 0,
            costBasis: 0,
            valuedPositions: 0,
        };
        // Coste con el MISMO multiplicador que la fila (opciones x100: el
        // coste medio es prima por acción, como en la contabilidad FIFO).
        const mult = position.kind === 'opcion' ? OPTION_MULTIPLIER : 1;
        total.marketValue = cents(total.marketValue + row.marketValue);
        total.unrealizedPnl = cents(total.unrealizedPnl + row.unrealizedPnl);
        total.costBasis = cents(total.costBasis + position.quantity * position.avgCost * mult);
        total.valuedPositions += 1;
        byCurrency.set(position.currency, total);
    });

    return {
        rows,
        totals: [...byCurrency.values()].sort((a, b) => a.currency.localeCompare(b.currency)),
        coverage: { valued: rows.filter((r) => r.status === 'valorada').length, total: rows.length },
    };
}

/** Clave unica de fila: la misma accion puede tener posiciones en dos divisas. */
export function valuationRowKey(row: { currency: ValuationCurrency; instrumentKey: string }): string {
    return `${row.currency}|${row.instrumentKey}`;
}

/** True si la valoracion corresponde EXACTAMENTE a las posiciones actuales (clave, cantidad y coste). */
export function valuationMatches(valuation: DemoValuation, positions: ValuationPosition[]): boolean {
    if (valuation.rows.length !== positions.length) return false;
    const byKey = new Map(valuation.rows.map((r) => [valuationRowKey(r), r]));
    return positions.every((p) => {
        const r = byKey.get(valuationRowKey(p));
        return r !== undefined && r.quantity === p.quantity && r.avgCost === p.avgCost && r.currency === p.currency;
    });
}
