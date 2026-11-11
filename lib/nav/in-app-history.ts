/**
 * Historial interno de la pestaña (solo navegaciones dentro de la app).
 *
 * Los enlaces «← Volver» de las fichas y subpáginas iban siempre a un padre
 * fijo (`/research`, `/research/NVDA`): quien llegaba desde la watchlist,
 * desde Inicio o desde una pestaña `?view=` de la ficha volvía a otro sitio,
 * con la vista y el scroll perdidos y la ficha entera renderizada otra vez.
 * En la app instalada en el iPhone (PWA) no hay botón atrás del navegador,
 * así que ese enlace es la única forma de volver.
 *
 * Este módulo guarda la pila de URLs internas que se han visitado en la
 * pestaña para que el enlace sepa si «atrás» del historial es un sitio de la
 * app (y cuál) o si la página se abrió directamente (enlace desde Telegram,
 * marcador): en ese caso el enlace sigue yendo a su padre de siempre.
 */

const MAX_ENTRIES = 50;

/** Añade `url` a la pila; si coincide con la penúltima, se trata como «atrás». */
export function recordNavigation(stack: readonly string[], url: string): readonly string[] {
    if (!url) return stack;
    const last = stack[stack.length - 1];
    if (last === url) return stack;
    if (stack.length >= 2 && stack[stack.length - 2] === url) return stack.slice(0, -1);
    const next = [...stack, url];
    return next.length > MAX_ENTRIES ? next.slice(next.length - MAX_ENTRIES) : next;
}

/** URL interna anterior a la actual, o null si la página se abrió directamente. */
export function previousInAppUrl(stack: readonly string[]): string | null {
    return stack.length >= 2 ? stack[stack.length - 2] : null;
}

function pathOf(url: string): string {
    const cut = url.search(/[?#]/);
    const path = cut === -1 ? url : url.slice(0, cut);
    return path.length > 1 ? path.replace(/\/+$/, '') : path;
}

/**
 * ¿El enlace «volver» debe usar el historial en vez de su `href`?
 *
 * - `sameDestinationOnly` (por defecto): solo si la página anterior es la
 *   misma ruta que el `href` del enlace («← NVDA» vuelve a la ficha de NVDA
 *   con su pestaña y su scroll; si se llegó desde la watchlist, el enlace
 *   sigue diciendo NVDA y va a NVDA).
 * - sin `sameDestinationOnly`: cualquier página interna anterior (enlace
 *   genérico «Volver»).
 */
export function shouldUseHistoryBack(
    stack: readonly string[],
    fallbackHref: string,
    sameDestinationOnly = true,
): boolean {
    const previous = previousInAppUrl(stack);
    if (!previous) return false;
    if (!sameDestinationOnly) return true;
    return pathOf(previous) === pathOf(fallbackHref);
}

let stackState: readonly string[] = [];
const listeners = new Set<() => void>();

export const inAppHistoryStore = {
    record(url: string): void {
        const next = recordNavigation(stackState, url);
        if (next === stackState) return;
        stackState = next;
        for (const listener of listeners) listener();
    },
    getSnapshot(): readonly string[] {
        return stackState;
    },
    getServerSnapshot(): readonly string[] {
        return EMPTY;
    },
    subscribe(listener: () => void): () => void {
        listeners.add(listener);
        return () => listeners.delete(listener);
    },
    /** Solo tests. */
    reset(): void {
        stackState = [];
    },
};

const EMPTY: readonly string[] = [];
