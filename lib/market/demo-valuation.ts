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
 * - Fuente aprobada: SOLO Finnhub. La accion no llama a Yahoo; ademas, como
 *   defensa, una cotizacion de otra fuente que llegara aqui sale N/D y no
 *   cuenta como valorada.
 * - Divisa: NUNCA se infiere del simbolo ni del sufijo. La divisa debe venir
 *   en ValuationQuote.currency, que la accion rellena SOLO con la divisa de
 *   cotizacion del listado US de Finnhub (/stock/symbol?exchange=US, campo
 *   currency). Solo 'EUR' y 'USD' exactos se valoran. Sin divisa verificada
 *   => N/D. Si no coincide con la divisa de la posicion => N/D (sin
 *   conversion).
 * - Opciones: la cotizacion del subyacente NO es la prima del contrato, asi
 *   que no se valoran. Se listan como "no valorada" con el motivo.
 * - Los totales suman SOLO las posiciones valoradas, por divisa, y se
 *   acompanan de la cobertura "N de M".
 */

// @ts-expect-error TS5097
import { DEFAULT_LOCALE, type Locale } from '../i18n/locale.ts';
// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';

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
    currencyBasis: 'finnhub-listado' | null;
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

export type QuoteCurrency = { currency: ValuationCurrency | null; basis: 'finnhub-listado' | null; reason: string | null };

/** Divisa de la cotizacion SOLO si viene verificada en quote.currency; nunca por sufijo ni por ausencia de el. */
export function resolveQuoteCurrency(quote: ValuationQuote, locale: Locale = DEFAULT_LOCALE): QuoteCurrency {
    const declared = typeof quote.currency === 'string' ? quote.currency.trim() : '';
    if (declared === 'EUR' || declared === 'USD') return { currency: declared, basis: 'finnhub-listado', reason: null };
    const t = createTranslator(locale);
    if (declared) return { currency: null, basis: null, reason: t('paperTrading.valuation.rowNotes.listingCurrency', { currency: declared }) };
    return { currency: null, basis: null, reason: t('paperTrading.valuation.rowNotes.currencyNotVerifiedListing') };
}

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

/**
 * Valora cada posicion con `quotes` (clave = simbolo en mayusculas). Un
 * simbolo ausente del mapa o con null cuenta como "sin cotizacion".
 */
export function valuePositions(
    positions: ValuationPosition[],
    quotes: Record<string, ValuationQuote | null | undefined>,
    options: { notQueried?: ReadonlySet<string>; currencyUnverified?: ReadonlySet<string>; locale?: Locale } = {},
): DemoValuation {
    const locale: Locale = options.locale ?? DEFAULT_LOCALE;
    const t = createTranslator(locale);
    const rows: ValuedPosition[] = positions.map((position) => {
        if (position.kind === 'opcion') {
            return unvalued(position, 'opcion-no-valorada', t('paperTrading.valuation.rowNotes.optionNotValued'));
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
        if (quote.source !== 'Finnhub') {
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
        total.marketValue = cents(total.marketValue + row.marketValue);
        total.unrealizedPnl = cents(total.unrealizedPnl + row.unrealizedPnl);
        total.costBasis = cents(total.costBasis + position.quantity * position.avgCost);
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
