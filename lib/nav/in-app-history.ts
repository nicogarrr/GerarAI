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

/** Record a PUSH. URL equality never establishes a browser POP. */
export function recordNavigation(stack: readonly string[], url: string): readonly string[] {
    if (!url) return stack;
    const last = stack[stack.length - 1];
    if (last === url) return stack;
    const next = [...stack, url];
    return next.length > MAX_ENTRIES ? next.slice(next.length - MAX_ENTRIES) : next;
}

/** Native anchor entries are browser history, but not a new page origin. */
export function historyBackSteps(stack: readonly string[]): number {
    const current = stack.at(-1)?.split('#')[0];
    for (let index = stack.length - 2; index >= 0; index--) {
        if (stack[index].split('#')[0] !== current) return stack.length - 1 - index;
    }
    return 0;
}

/** Previous distinct in-app destination, excluding anchors on the same page. */
export function previousInAppUrl(stack: readonly string[]): string | null {
    const steps = historyBackSteps(stack);
    return steps ? stack[stack.length - 1 - steps] : null;
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
let notificationQueued = false;

function notifyAfterCommit(): void {
    if (notificationQueued) return;
    notificationQueued = true;
    queueMicrotask(() => {
        notificationQueued = false;
        for (const listener of listeners) listener();
    });
}

export const inAppHistoryStore = {
    replaceStack(stack: readonly string[]): void {
        stackState = stack;
        // Navigation API events can fire in Next's useInsertionEffect.
        // Keep entry identity current, but notify React after its commit.
        notifyAfterCommit();
    },
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
