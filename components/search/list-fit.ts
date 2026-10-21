/**
 * Geometría pura de la lista del buscador con dirección forzada ("bottom").
 *
 * Regla invariante: la altura máxima de la lista NO supera el espacio real
 * disponible bajo el input dentro del visual viewport — el suelo es 0, sin
 * mínimos mágicos que la pudieran empujar bajo el teclado. Si el hueco es
 * incómodo (< LIST_COMFORTABLE_SPACE) se intenta crear espacio desplazando
 * la página UNA única vez por apertura (lo gobierna el componente con una
 * guardia), y la re-medición vía listeners del visualViewport recalcula.
 */

/** Techo absoluto de la lista en px (espacios grandes). */
export const LIST_MAX_HEIGHT_CAP = 240;
/** Por debajo de este hueco la lista cabe pero resulta incómoda: se pide
 *  el reposicionamiento (una vez por apertura). */
export const LIST_COMFORTABLE_SPACE = 96;
/** Margen entre el borde inferior del input y el inicio de la lista. */
export const LIST_GAP = 8;

/** Espacio real bajo el input dentro del visual viewport.
 *  viewportOffsetTop importa: con el teclado o las barras de Safari el
 *  viewport no empieza en 0. Puede salir negativo (input bajo el pliegue). */
export function computeSpaceBelow(inputBottom: number, viewportHeight: number, viewportOffsetTop: number, gap: number = LIST_GAP): number {
    const viewportBottom = viewportOffsetTop + viewportHeight;
    return Math.floor(viewportBottom - inputBottom - gap);
}

export interface ListFit {
    /** px; NUNCA supera el espacio real disponible (mínimo 0, techo 240). */
    maxHeight: number;
    /** true si conviene crear hueco desplazando la página (solo si aún no
     *  se hizo en esta apertura). */
    shouldScroll: boolean;
}

export function computeListFit(spaceBelow: number, alreadyScrolled: boolean): ListFit {
    const maxHeight = Math.max(0, Math.min(LIST_MAX_HEIGHT_CAP, spaceBelow));
    return { maxHeight, shouldScroll: spaceBelow < LIST_COMFORTABLE_SPACE && !alreadyScrolled };
}
