/**
 * Cadena de fuentes de logo, en orden, para un ticker:
 *  1. FMP image-stock (pública y gratuita, por símbolo de listado).
 *  2. /api/logo/<ticker>: icono oficial de la web de la empresa, servido y
 *     cacheado por nuestra propia ruta (sin proveedores de logos de terceros).
 * Si ninguna da un logo visible, CompanyLogo pinta las iniciales (NameAvatar).
 */
export function logoSources(ticker: string): string[] {
    const t = encodeURIComponent(ticker.trim());
    if (!t) return [];
    return [`https://financialmodelingprep.com/image-stock/${t}.png`, `/api/logo/${t}`];
}

/** Fondo para un glifo claro sobre transparente (UBER, UNH, HIMS, V). */
export const DARK_LOGO_BACKGROUND = 'rgb(24, 24, 27)';
