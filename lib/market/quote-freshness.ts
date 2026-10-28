/**
 * F358: clasifica la frescura de una cotizacion por el timestamp `t` que
 * adjunta el proveedor, con semantica de sesion del mercado US
 * (America/New_York, lun-vie 9:30-16:00).
 *
 * Por que existe: fetchJSON usa force-cache + revalidate; con errores
 * sostenidos del proveedor (429 por cuota, F357) Next sirve el ultimo valor
 * bueno INDEFINIDAMENTE (stale-while-error) y el fetch resuelve 200 con la
 * cotizacion de ayer sin que el error llegue al catch. La unica senal de
 * frescura es el timestamp de la propia cotizacion.
 *
 * Semantica de mercado cerrado: una cotizacion vieja no es "actual", es el
 * ULTIMO CIERRE FECHADO - dato legitimo si se etiqueta como cierre.
 *
 * - 'live':   mercado abierto y `t` dentro de la sesion de hoy.
 * - 'close':  `t` pertenece a la ultima sesion completada (noche, finde,
 *             pre-market). Dato correcto, pero es un cierre, no "ahora".
 * - 'stale':  mas viejo que la ultima sesion (p.ej. cache de ayer servida
 *             durante la sesion de hoy) o timestamp roto/futuro: se rechaza.
 *
 * Festivos US: se tratan como dia de sesion; un cierre de ayer un festivo
 * clasifica 'close' (conservador y honesto: ES el ultimo cierre real).
 *
 * Modulo PURO: sin imports de servidor, para poder probarlo con node --test.
 */

export type QuoteKind = 'live' | 'close' | 'stale';

const ET_ZONE = 'America/New_York';

type EtParts = {
    year: number;
    month: number;
    day: number;
    hour: number;
    minute: number;
    weekday: number; // 0=domingo .. 6=sabado
};

const ET_FORMAT = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    weekday: 'short',
});

const WEEKDAY_INDEX: Record<string, number> = {
    Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
};

function etParts(ms: number): EtParts {
    const parts = ET_FORMAT.formatToParts(new Date(ms));
    const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? '';
    return {
        year: Number(get('year')),
        month: Number(get('month')),
        day: Number(get('day')),
        hour: Number(get('hour')),
        minute: Number(get('minute')),
        weekday: WEEKDAY_INDEX[get('weekday')] ?? 0,
    };
}

/** Convierte una hora wall-clock de Nueva York a ms UTC (una iteracion basta:
 * el offset solo se desvia 1h en transiciones DST, lejos de 9:30/16:00). */
function etWallToUtcMs(year: number, month: number, day: number, hour: number, minute: number): number {
    const guess = Date.UTC(year, month - 1, day, hour, minute);
    const actual = etParts(guess);
    const deltaMs =
        Date.UTC(year, month - 1, day, hour, minute) -
        Date.UTC(actual.year, actual.month - 1, actual.day, actual.hour, actual.minute);
    return guess + deltaMs;
}

/** Desplaza una fecha ET en dias y devuelve sus partes de fecha. */
function shiftEtDate(year: number, month: number, day: number, deltaDays: number): { year: number; month: number; day: number } {
    // Mediodia UTC cae siempre dentro del mismo dia ET (offset 4-5h).
    const shifted = etParts(Date.UTC(year, month - 1, day + deltaDays, 12, 0));
    return { year: shifted.year, month: shifted.month, day: shifted.day };
}

/** Apertura (9:30 ET) de la ultima sesion completada, para "ahora" fuera de sesion. */
function lastCompletedSessionOpenMs(now: EtParts): number {
    // domingo -> viernes (-2), sabado -> viernes (-1), lunes -> viernes (-3),
    // mar-vie antes de la apertura -> ayer (-1).
    const delta = now.weekday === 0 ? -2 : now.weekday === 1 ? -3 : -1;
    const session = shiftEtDate(now.year, now.month, now.day, delta);
    return etWallToUtcMs(session.year, session.month, session.day, 9, 30);
}

export function classifyQuoteKind(tSeconds: number, nowMs: number = Date.now()): QuoteKind {
    if (!Number.isFinite(tSeconds) || tSeconds <= 0) return 'stale';
    const tMs = tSeconds * 1000;
    // Timestamp en el futuro (margen 15 min de skew) = dato roto, no fresco.
    if (tMs > nowMs + 15 * 60 * 1000) return 'stale';
    const now = etParts(nowMs);
    const isWeekday = now.weekday >= 1 && now.weekday <= 5;
    if (isWeekday) {
        const openMs = etWallToUtcMs(now.year, now.month, now.day, 9, 30);
        const closeMs = etWallToUtcMs(now.year, now.month, now.day, 16, 0);
        if (nowMs >= openMs && nowMs < closeMs) {
            // Sesion en curso: solo vale lo de ESTA sesion.
            return tMs >= openMs ? 'live' : 'stale';
        }
        if (nowMs >= closeMs) {
            // Tras el cierre: la sesion de hoy es el ultimo cierre fechado.
            return tMs >= openMs ? 'close' : 'stale';
        }
    }
    // Pre-market o fin de semana: referencia = ultima sesion completada.
    return tMs >= lastCompletedSessionOpenMs(now) ? 'close' : 'stale';
}

/** Fecha de sesion ET (YYYY-MM-DD) de una cotizacion, para etiquetar el cierre. */
export function sessionDateEt(tSeconds: number): string {
    const p = etParts(tSeconds * 1000);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

/** Cotizacion saneada: shape Finnhub {c,d,dp,h,l,o,pc} + frescura validada. */
export type SanitizedQuote = {
    source?: 'Finnhub' | 'Yahoo Finance';
    /** d/dp son null cuando el proveedor no tiene cierre previo real (nunca un 0 inventado). */
    c: number; d: number | null; dp: number | null; h: number; l: number; o: number; pc: number;
    /** Timestamp (epoch s) del proveedor; null en el fallback Yahoo (sin fecha). */
    t: number | null;
    /** Market-local date of the exact daily candle c, supplied by Yahoo backend. */
    closeDate?: string | null;
    /** 'live' = sesion en curso; 'close' = ultimo cierre fechado. 'stale' nunca se devuelve. */
    kind: 'live' | 'close';
    /**
     * Unidad declarada por el proveedor para c/d/h/l/o/pc (Yahoo: «GBp» en
     * Londres = peniques). Ausente si el proveedor no la declara (Finnhub).
     */
    currency?: string | null;
};

/**
 * F358: valida una cotizacion Finnhub por su propio timestamp antes de
 * aceptarla. Con errores sostenidos del proveedor (429 por cuota, F357) la
 * Data Cache de Next sirve el ultimo valor bueno INDEFINIDAMENTE
 * (stale-while-error): el fetch resuelve 200 con el dato viejo y el error
 * nunca llega al catch. La unica senal de frescura es `t`. null = miss honesto.
 */
/**
 * Forma mínima de una cotización de proveedor: Finnhub quote o vela diaria
 * del backend Yahoo (`cd` = fecha de la vela). Todo opcional: se valida por
 * campo. Los huecos numéricos se sirven como 0 (antes se colaba `undefined`
 * en campos tipados como number).
 */
export interface ProviderQuotePayload {
    c?: number | null;
    d?: number | null;
    dp?: number | null;
    h?: number | null;
    l?: number | null;
    o?: number | null;
    pc?: number | null;
    t?: number | null;
    /** Variantes de timestamp que devuelve Finnhub en respuestas cacheadas. */
    ct?: unknown;
    cd?: unknown;
    /** Unidad de la cotización (backend Yahoo: p. ej. «GBp» = peniques). */
    currency?: unknown;
}

export function sanitizeFinnhubQuote(data: ProviderQuotePayload | null | undefined, nowMs: number = Date.now()): SanitizedQuote | null {
    if (!data || !((data.c ?? 0) > 0 || (data.pc ?? 0) > 0)) return null;
    const t = typeof data.t === 'number' && Number.isFinite(data.t) ? data.t : 0;
    const kind = classifyQuoteKind(t, nowMs);
    if (kind === 'stale') return null;
    return { source: 'Finnhub', c: data.c ?? 0, d: data.d ?? 0, dp: data.dp ?? 0, h: data.h ?? 0, l: data.l ?? 0, o: data.o ?? 0, pc: data.pc ?? 0, t, kind };
}

/** Validate a date without timezone shifts or accepting JS calendar overflow. */
function validCalendarDate(value: unknown): string | null {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const parsed = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
}

/** Yahoo daily close: use only the exact candle's date cd, never retrieval time. */
export function mapBackendYahooQuote(data: ProviderQuotePayload | null | undefined): SanitizedQuote | null {
    if (!data || !((data.c ?? 0) > 0 || (data.pc ?? 0) > 0)) return null;
    const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    return {
        c: num(data.c),
        // Sin cierre previo real el backend manda null: no se convierte en 0,00 %.
        d: typeof data.d === 'number' && Number.isFinite(data.d) ? data.d : null,
        dp: typeof data.dp === 'number' && Number.isFinite(data.dp) ? data.dp : null,
        h: num(data.h), l: num(data.l), o: num(data.o), pc: num(data.pc),
        source: 'Yahoo Finance', t: null, kind: 'close',
        closeDate: validCalendarDate(data.cd),
        // Solo si el backend la declara (contrato estable sin ella).
        ...(typeof data.currency === 'string' && data.currency.trim() ? { currency: data.currency.trim() } : {}),
    };
}
