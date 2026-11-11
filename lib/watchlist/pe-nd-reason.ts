/**
 * Motivo visible del PER «N/D» en la watchlist (tarjeta móvil y tabla).
 *
 * El backend ya explica cada N/D en su fuente («PER: N/D: eps_diluted FY2025 =
 * -0.47 (SEC): sin beneficio no hay PER», «… en TWD y cierre del listado en
 * USD: mezclar divisas fabrica el ratio»), pero la celda solo pintaba «N/D»:
 * el motivo quedaba en un title que en el iPhone no se ve. Aquí se traduce a
 * una nota corta; la cadena completa sigue en el title para la trazabilidad.
 * Mismas reglas para todas las empresas: se lee el motivo, nunca el ticker.
 */

export type PeNdKey =
    | 'watchlist.page.peNd.loss'
    | 'watchlist.page.peNd.lossUndated'
    | 'watchlist.page.peNd.currency'
    | 'watchlist.page.peNd.fx'
    | 'watchlist.page.peNd.split'
    | 'watchlist.page.peNd.stale'
    | 'watchlist.page.peNd.staleUndated'
    | 'watchlist.page.peNd.other'
    | 'watchlist.page.readTimedOut'
    | 'watchlist.page.readFailed'
    | 'watchlist.page.peNotCovered';

export type PeNdNote = { key: PeNdKey; params?: Record<string, string> };

export type PeNdInput = {
    peRatio: number | null;
    peSource: string | null;
    timedOut?: boolean;
    metricsNotApplicable?: boolean;
    /** La lectura del backend falló: el PER puede existir (no es «no cubre»). */
    metricsReadFailed?: boolean;
};

const ND_PREFIX = /^PER:\s*N\/D:\s*/i;

/** Clasifica la cadena «PER: N/D: …» del backend; null si no es un N/D explicado. */
export function peNdReasonFromSource(source: string | null | undefined): PeNdNote | null {
    if (!source || !ND_PREFIX.test(source)) return null;
    const detail = source.replace(ND_PREFIX, '');
    const year = /FY(\d{4})/.exec(detail)?.[1];
    if (/sin beneficio/i.test(detail)) {
        return year ? { key: 'watchlist.page.peNd.loss', params: { year } } : { key: 'watchlist.page.peNd.lossUndated' };
    }
    const mix = /en ([A-Z]{3}) y cierre del listado en ([A-Z]{3})/.exec(detail);
    if (mix) return { key: 'watchlist.page.peNd.currency', params: { eps: mix[1], quote: mix[2] } };
    if (/sin tipo de cambio/i.test(detail)) return { key: 'watchlist.page.peNd.fx' };
    if (/split/i.test(detail)) return { key: 'watchlist.page.peNd.split' };
    if (/m[aá]s de 18|hace \d+ meses/i.test(detail)) {
        return year ? { key: 'watchlist.page.peNd.stale', params: { year } } : { key: 'watchlist.page.peNd.staleUndated' };
    }
    return { key: 'watchlist.page.peNd.other' };
}

/**
 * Nota bajo el «N/D» del PER, por prioridad: lectura cortada (no es un fallo
 * de la fuente), motivo del backend, mercado sin cobertura. Null con PER.
 */
export function peNdNote(stock: PeNdInput): PeNdNote | null {
    if (stock.peRatio !== null && Number.isFinite(stock.peRatio)) return null;
    if (stock.timedOut) return { key: 'watchlist.page.readTimedOut' };
    const reason = peNdReasonFromSource(stock.peSource);
    if (reason) return reason;
    if (stock.metricsReadFailed) return { key: 'watchlist.page.readFailed' };
    if (stock.metricsNotApplicable) return { key: 'watchlist.page.peNotCovered' };
    return null;
}
