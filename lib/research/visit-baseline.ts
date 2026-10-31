/**
 * Referencia de "ultima visita" por empresa, solo en este navegador.
 *
 * - `localStorage` guarda cuando entraste por ultima vez.
 * - `sessionStorage` congela la referencia durante la sesion: recargar la
 *   pagina no borra el diff que aun no has leido.
 * Funcion pura sobre un `Storage` inyectado para poder probarla sin navegador.
 */
export interface StorageLike {
    getItem(key: string): string | null;
    setItem(key: string, value: string): void;
}

const keyFor = (ticker: string) => ticker.toUpperCase();

/** Devuelve la fecha ISO desde la que comparar, o null si es la primera visita. */
export function resolveVisitBaseline(
    local: StorageLike,
    session: StorageLike,
    ticker: string,
    now: Date,
): string | null {
    const key = keyFor(ticker);
    const frozen = session.getItem(`cavaai:visit-baseline:${key}`);
    let baseline: string | null;
    if (frozen !== null) {
        baseline = frozen === '' ? null : frozen;
    } else {
        const previous = local.getItem(`cavaai:last-visit:${key}`);
        baseline = previous && !Number.isNaN(Date.parse(previous)) ? previous : null;
        session.setItem(`cavaai:visit-baseline:${key}`, baseline ?? '');
    }
    local.setItem(`cavaai:last-visit:${key}`, now.toISOString());
    return baseline;
}

/** «Marcar como leído»: la referencia pasa a ahora en este navegador (sin tocar el servidor). */
export function markVisitRead(local: StorageLike, session: StorageLike, ticker: string, now: Date): void {
    const key = keyFor(ticker);
    const iso = now.toISOString();
    session.setItem(`cavaai:visit-baseline:${key}`, iso);
    local.setItem(`cavaai:last-visit:${key}`, iso);
}
