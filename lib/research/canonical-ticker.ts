/**
 * Un ticker con sufijo de mercado (SAN.MC, ASML.AS, AENA.MC) es la misma
 * empresa que su ticker base cuando el backend lo resuelve a ese base
 * (company_resolver: el match exacto siempre gana, el sufijo es solo
 * fallback). La ficha del ticker con sufijo no tiene identidad de mercado
 * verificada (precio N/D), asi que se redirige a la ficha canonica.
 *
 * Solo redirige si lo resuelto es EXACTAMENTE el prefijo antes del punto:
 * tickers reales con punto (BRK.B) y cualquier resolucion distinta no se tocan.
 */
export function canonicalRedirectTicker(requested: string, resolved: string | null | undefined): string | null {
    const req = requested.trim().toUpperCase();
    const res = (resolved ?? '').trim().toUpperCase();
    if (!res || res === req) return null;
    const dot = req.lastIndexOf('.');
    if (dot <= 0) return null;
    return req.slice(0, dot) === res ? res : null;
}
