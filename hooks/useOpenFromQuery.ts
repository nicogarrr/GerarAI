import { useEffect } from 'react';

/**
 * Parámetro de URL que abre un diálogo de alta al llegar a la página
 * (`/portfolio?anadir=1`, `/watchlist?anadir=1`). Lo usan los enlaces de
 * «Primeros pasos» de Inicio: antes llevaban a la página y el usuario tenía
 * que buscar y pulsar otra vez «Añadir…».
 */
export const OPEN_ADD_DIALOG_PARAM = 'anadir';

/**
 * Devuelve true (una sola vez) si la URL trae `?<param>=1` y quita el
 * parámetro de la barra de direcciones. El primer componente que lo lee se lo
 * queda: con varios botones iguales en la página solo se abre un diálogo, y
 * recargar o volver atrás no lo reabre.
 */
export function consumeOpenParam(param: string = OPEN_ADD_DIALOG_PARAM): boolean {
    if (typeof window === 'undefined') return false;
    const url = new URL(window.location.href);
    if (url.searchParams.get(param) !== '1') return false;
    url.searchParams.delete(param);
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
    return true;
}

/** Llama a `open` al montar si la URL pide abrir el diálogo de alta. */
export function useOpenFromQuery(open: () => void, param: string = OPEN_ADD_DIALOG_PARAM) {
    useEffect(() => {
        if (consumeOpenParam(param)) open();
        // Solo al montar: el parámetro se consume una vez.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
}
