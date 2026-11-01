import type { FinnhubProfile2 } from '@/lib/actions/finnhub.actions';
import { resolveUnknownListingIdentity } from '@/lib/research/unknown-listing';

/**
 * Ticker «no encontrado» en la watchlist: mismo criterio que la ficha
 * research (/research/<ticker>, estado «No encontramos este ticker en
 * nuestras fuentes»). Solo cuando el símbolo NO está en el master de GerarAI
 * y el proveedor de mercado respondió sin perfil propio. Proveedor caído
 * (perfil null) = no se sabe: sin etiqueta, nunca «no encontrado».
 * La fila NO se rechaza ni se borra: solo se rotula.
 */
export function isTickerNotFound(
    basics: unknown | null,
    profile: FinnhubProfile2 | null,
    ticker: string,
): boolean {
    if (basics) return false;
    return resolveUnknownListingIdentity(profile, ticker).kind === 'not-in-sources';
}
