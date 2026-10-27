/**
 * ¿La última vela diaria del gráfico es ya un cierre o puede ser parcial?
 *
 * Antes la cabecera comparaba la fecha de la vela con «hoy en Nueva York» para
 * TODOS los listados: la vela de hoy de CGEO.L o SAN.MC seguía rotulada
 * «puede ser parcial» toda la tarde aunque Londres/Madrid ya hubieran cerrado.
 * Aquí se usa el huso y la hora de cierre del propio mercado (más un margen
 * para la subasta y la publicación del dato). Un mercado que no está en la
 * tabla conserva el criterio prudente de antes: solo es cierre una vela de un
 * día anterior al de hoy en Nueva York.
 */

type Session = { tz: string; closeMinutes: number };

const EURONEXT: Session = { tz: 'Europe/Paris', closeMinutes: 17 * 60 + 35 };

/** Sufijo Yahoo -> huso del mercado y cierre local (minutos desde medianoche). */
const SESSIONS_BY_SUFFIX: Record<string, Session> = {
    L: { tz: 'Europe/London', closeMinutes: 16 * 60 + 35 },
    MC: { tz: 'Europe/Madrid', closeMinutes: 17 * 60 + 35 },
    PA: EURONEXT,
    AS: { ...EURONEXT, tz: 'Europe/Amsterdam' },
    BR: { ...EURONEXT, tz: 'Europe/Brussels' },
    LS: { tz: 'Europe/Lisbon', closeMinutes: 16 * 60 + 35 },
    DE: { tz: 'Europe/Berlin', closeMinutes: 17 * 60 + 35 },
    F: { tz: 'Europe/Berlin', closeMinutes: 17 * 60 + 35 },
    MI: { tz: 'Europe/Rome', closeMinutes: 17 * 60 + 35 },
    SW: { tz: 'Europe/Zurich', closeMinutes: 17 * 60 + 30 },
    TO: { tz: 'America/Toronto', closeMinutes: 16 * 60 },
};

const US_SESSION: Session = { tz: 'America/New_York', closeMinutes: 16 * 60 };

/** Margen tras el cierre oficial (subasta de cierre + retraso del proveedor). */
const SETTLE_MINUTES = 15;

function localParts(now: Date, tz: string): { date: string; minutes: number } {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(now);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00';
    return { date: `${get('year')}-${get('month')}-${get('day')}`, minutes: Number(get('hour')) * 60 + Number(get('minute')) };
}

export function listingSession(symbol: string | null | undefined, currency: string | null | undefined): Session | null {
    const s = (symbol ?? '').trim().toUpperCase();
    const dot = s.lastIndexOf('.');
    if (dot > 0) {
        // BRK.B / BF.B: clase de acción de EE. UU., no sufijo de mercado.
        const suffix = s.slice(dot + 1);
        if (SESSIONS_BY_SUFFIX[suffix]) return SESSIONS_BY_SUFFIX[suffix];
        if (suffix.length === 1 && (currency ?? '').toUpperCase() === 'USD') return US_SESSION;
        return null;
    }
    return s && (currency ?? '').toUpperCase() === 'USD' ? US_SESSION : null;
}

export function isClosedCandle(
    candleDate: string,
    opts: { symbol?: string | null; currency?: string | null; now?: Date },
): boolean {
    const day = candleDate.slice(0, 10);
    const now = opts.now ?? new Date();
    const session = listingSession(opts.symbol, opts.currency);
    if (!session) return day < localParts(now, US_SESSION.tz).date;
    const local = localParts(now, session.tz);
    if (day < local.date) return true;
    return day === local.date && local.minutes >= session.closeMinutes + SETTLE_MINUTES;
}
