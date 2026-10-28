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

/**
 * Hora OFICIAL de cierre de cada mercado, en su hora local; el horario de
 * verano lo resuelve el huso IANA (Intl), nunca un desfase fijo. La subasta de
 * cierre (LSE 16:30-16:35, BME/Xetra/Milán 17:30-17:35) y el retraso del
 * proveedor quedan cubiertos por SETTLE_MINUTES.
 *   LSE 16:30 Londres · BME 17:30 Madrid · Euronext (París, Ámsterdam,
 *   Bruselas) 17:30 CET · Euronext Lisboa 16:30 Lisboa (= 17:30 CET) ·
 *   Xetra 17:30 Fráncfort · Börse Frankfurt (parqué, .F) 22:00 ·
 *   Borsa Italiana 17:30 Milán · SIX 17:30 Zúrich · TSX 16:00 Toronto ·
 *   EE. UU. 16:00 Nueva York.
 */
const at = (h: number, m = 0) => h * 60 + m;

/** Sufijo Yahoo -> huso del mercado y cierre oficial local. */
const SESSIONS_BY_SUFFIX: Record<string, Session> = {
    L: { tz: 'Europe/London', closeMinutes: at(16, 30) },
    MC: { tz: 'Europe/Madrid', closeMinutes: at(17, 30) },
    PA: { tz: 'Europe/Paris', closeMinutes: at(17, 30) },
    AS: { tz: 'Europe/Amsterdam', closeMinutes: at(17, 30) },
    BR: { tz: 'Europe/Brussels', closeMinutes: at(17, 30) },
    LS: { tz: 'Europe/Lisbon', closeMinutes: at(16, 30) },
    DE: { tz: 'Europe/Berlin', closeMinutes: at(17, 30) },
    // .F es el parqué de Börse Frankfurt (hasta las 22:00), no Xetra.
    F: { tz: 'Europe/Berlin', closeMinutes: at(22) },
    MI: { tz: 'Europe/Rome', closeMinutes: at(17, 30) },
    SW: { tz: 'Europe/Zurich', closeMinutes: at(17, 30) },
    TO: { tz: 'America/Toronto', closeMinutes: at(16) },
};

const US_SESSION: Session = { tz: 'America/New_York', closeMinutes: at(16) };

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
