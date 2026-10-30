import { useEffect } from 'react';
import { OPEN_ADD_DIALOG_PARAM, OPEN_ADD_SYMBOL_PARAM } from '@/lib/portfolio/add-dialog-link';

export { OPEN_ADD_DIALOG_PARAM, OPEN_ADD_SYMBOL_PARAM };

export type OpenRequest = { symbol: string | null };

/**
 * Devuelve la petición (una sola vez) si la URL trae `?<param>=1` y quita los
 * parámetros de la barra de direcciones. El primer componente que lo lee se lo
 * queda: con varios botones iguales en la página solo se abre un diálogo, y
 * recargar o volver atrás no lo reabre. Sin la petición devuelve null.
 */
export function consumeOpenParam(param: string = OPEN_ADD_DIALOG_PARAM): OpenRequest | null {
    if (typeof window === 'undefined') return null;
    const url = new URL(window.location.href);
    if (url.searchParams.get(param) !== '1') return null;
    const symbol = url.searchParams.get(OPEN_ADD_SYMBOL_PARAM)?.trim() || null;
    url.searchParams.delete(param);
    url.searchParams.delete(OPEN_ADD_SYMBOL_PARAM);
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
    return { symbol };
}

/** Llama a `open` al montar si la URL pide abrir el diálogo de alta. */
export function useOpenFromQuery(open: (request: OpenRequest) => void, param: string = OPEN_ADD_DIALOG_PARAM) {
    useEffect(() => {
        const request = consumeOpenParam(param);
        if (request) open(request);
        // Solo al montar: el parámetro se consume una vez.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
}
