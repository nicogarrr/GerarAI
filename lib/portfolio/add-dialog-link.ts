/**
 * Enlaces que abren un diálogo de alta al llegar a la página
 * (`/portfolio?anadir=1`, `/watchlist?anadir=1`), con el símbolo ya elegido
 * si viene `simbolo`. Módulo sin React: lo usan también server components
 * (ficha) para construir el enlace; el hook que lo lee vive en
 * hooks/useOpenFromQuery.ts.
 */
export const OPEN_ADD_DIALOG_PARAM = 'anadir';
export const OPEN_ADD_SYMBOL_PARAM = 'simbolo';

/** Alta de una operación con el símbolo ya elegido («Tu posición» de la ficha). */
export function addTransactionHref(symbol: string): string {
    return `/portfolio?${OPEN_ADD_DIALOG_PARAM}=1&${OPEN_ADD_SYMBOL_PARAM}=${encodeURIComponent(symbol)}`;
}
