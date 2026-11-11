/**
 * Posición de scroll por página visitada, para volver «a donde estabas».
 *
 * Auditoría de flujo r5 (11-nov-2026), medida en un `next build` a 390 y
 * 1440 px: tras bajar ~900 px por la ficha, «← Volver a NVDA» (historial)
 * dejaba la ficha ARRIBA (scrollY 0) y el «atrás» del navegador desde el
 * Informe la dejaba en 1525 / 1818 px, que no es donde se estaba. El App
 * Router no restaura el scroll al volver por historial: lo hace el navegador
 * con lo que guardó al hacer `pushState`, y para entonces la página nueva ya
 * se ha pintado (o su `loading.tsx` ha encogido el documento), así que lo
 * guardado es la posición recortada, no la del usuario. Y al volver, la ficha
 * llega por streaming: el documento aún no mide lo bastante y el navegador
 * vuelve a recortar.
 *
 * Aquí: reglas puras (sin DOM) para guardar la última posición conocida de
 * cada URL interna y para decidir, fotograma a fotograma, cuándo la
 * restauración ha terminado. El componente ScrollPreserver las conecta.
 */

export const SCROLL_MEMORY_KEY = 'gerarai:scroll-memory:v1';
const MAX_ENTRIES = 50;

export type ScrollMemory = Readonly<Record<string, number>>;

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

/** Lee la memoria de sessionStorage (ilegible o ausente → vacía). */
export function readScrollMemory(storage: StorageLike | null | undefined): ScrollMemory {
    if (!storage) return {};
    try {
        const raw = storage.getItem(SCROLL_MEMORY_KEY);
        if (!raw) return {};
        const parsed: unknown = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
        const out: Record<string, number> = {};
        for (const [url, y] of Object.entries(parsed as Record<string, unknown>)) {
            if (typeof y === 'number' && Number.isFinite(y) && y >= 0) out[url] = y;
        }
        return out;
    } catch {
        return {};
    }
}

/** Guarda `y` para `url` (la más reciente al final; tope de entradas). */
export function rememberScroll(memory: ScrollMemory, url: string, y: number): ScrollMemory {
    if (!url || !Number.isFinite(y)) return memory;
    const value = Math.max(0, Math.round(y));
    if (memory[url] === value) return memory;
    const { [url]: _previous, ...rest } = memory;
    const next: Record<string, number> = { ...rest, [url]: value };
    const urls = Object.keys(next);
    if (urls.length > MAX_ENTRIES) {
        for (const old of urls.slice(0, urls.length - MAX_ENTRIES)) delete next[old];
    }
    return next;
}

export function writeScrollMemory(storage: StorageLike | null | undefined, memory: ScrollMemory): void {
    if (!storage) return;
    try {
        storage.setItem(SCROLL_MEMORY_KEY, JSON.stringify(memory));
    } catch {
        // Cuota llena o modo privado: sin memoria, el comportamiento es el de antes.
    }
}

/** Tiempo máximo intentando restaurar mientras la página termina de llegar. */
export const RESTORE_TIMEOUT_MS = 4000;
/** Fotogramas seguidos en el objetivo para dar la restauración por buena. */
export const RESTORE_STABLE_FRAMES = 5;

export type RestoreFrame = {
    /** Objetivo guardado. */
    target: number;
    /** scrollY actual. */
    y: number;
    /** Máximo desplazamiento posible ahora (scrollHeight − innerHeight). */
    maxY: number;
    /** Fotogramas seguidos ya en el objetivo. */
    stableFrames: number;
    /** ms desde que empezó la restauración. */
    elapsedMs: number;
};

export type RestoreStep =
    | { kind: 'scroll'; to: number; stableFrames: number }
    | { kind: 'done' }
    | { kind: 'give-up' };

/**
 * Un fotograma de la restauración. Mientras el documento no mide lo bastante
 * (la ficha llega por streaming) se baja hasta donde se pueda y se sigue
 * intentando; se da por terminada cuando la posición aguanta en el objetivo
 * varios fotogramas seguidos (absorbe los saltos de maquetación de lo que
 * llega por encima). Pasado el tiempo máximo se deja donde esté.
 */
export function restoreStep(frame: RestoreFrame): RestoreStep {
    const { target, y, maxY, stableFrames, elapsedMs } = frame;
    const reachable = maxY >= target - 1;
    const atTarget = reachable && Math.abs(y - target) <= 1;
    if (atTarget) {
        const stable = stableFrames + 1;
        return stable >= RESTORE_STABLE_FRAMES ? { kind: 'done' } : { kind: 'scroll', to: target, stableFrames: stable };
    }
    if (elapsedMs >= RESTORE_TIMEOUT_MS) return { kind: 'give-up' };
    return { kind: 'scroll', to: Math.min(target, Math.max(0, maxY)), stableFrames: 0 };
}
