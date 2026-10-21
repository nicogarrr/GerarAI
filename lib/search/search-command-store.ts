// Sin directiva "use client": el módulo entra en el bundle cliente a
// través de SearchCommand (que sí la tiene); directiva aquí sería ruido
// (guard no-useless-use-client).
//
// Owner único del buscador global. Header monta varias instancias de
// SearchCommand (botón desktop, icono móvil, drawer). Antes cada una tenía
// su propio `open` y su propio listener de Ctrl+K, así que el atajo abría
// TODOS los diálogos a la vez, apilados píxel a píxel: dos role="dialog"
// activos, alerts duplicados y foco/aria confusos. Aquí vive un único
// estado: el atajo o el clic eligen UNA instancia dueña (la del gatillo
// visible) y solo ella monta el CommandDialog.

export interface SearchCommandInstance {
    id: string;
    /** true cuando el gatillo de esta instancia está visible en viewport. */
    isTriggerVisible: () => boolean;
    /** Guarda document.activeElement para devolver el foco al cerrar. */
    captureReturnFocus: () => void;
}

export interface SearchCommandStoreState {
    open: boolean;
    /** Sticky tras cerrar: la misma instancia sigue montando su diálogo
        (cerrado) para que Radix complete animación y devolución de foco. */
    ownerId: string | null;
}

let state: SearchCommandStoreState = { open: false, ownerId: null };
const listeners = new Set<() => void>();
const instances = new Map<string, SearchCommandInstance>();
const registrationOrder: string[] = [];

function emit(): void {
    listeners.forEach((listener) => listener());
}

export function subscribeSearchCommand(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

export function getSearchCommandSnapshot(): SearchCommandStoreState {
    return state;
}

export function registerSearchCommandInstance(instance: SearchCommandInstance): () => void {
    instances.set(instance.id, instance);
    registrationOrder.push(instance.id);
    return () => {
        instances.delete(instance.id);
        const index = registrationOrder.indexOf(instance.id);
        if (index >= 0) registrationOrder.splice(index, 1);
        // Dueña desmontada con el diálogo abierto (p. ej. el drawer móvil se
        // cierra por Escape o al cruzar el breakpoint): sin este cierre el
        // store quedaba open=true con owner huérfano y el siguiente Ctrl+K
        // solo "cerraba" un diálogo fantasma en vez de abrir. El foco cae al
        // body: el gatillo original ya no existe. No afecta al cierre normal
        // (closeSearchCommand mantiene owner sticky para animación/foco).
        if (state.ownerId === instance.id) {
            state = { open: false, ownerId: null };
            emit();
        }
    };
}

export function openSearchCommand(ownerId: string): void {
    instances.get(ownerId)?.captureReturnFocus();
    state = { open: true, ownerId };
    emit();
}

export function closeSearchCommand(): void {
    if (!state.open) return;
    state = { ...state, open: false };
    emit();
}

function pickKeyboardOwner(): string | null {
    // El atajo abre la instancia cuyo gatillo está visible (botón en PC,
    // icono en móvil); si ninguno lo está, la primera registrada.
    for (const id of registrationOrder) {
        if (instances.get(id)?.isTriggerVisible()) return id;
    }
    return registrationOrder[0] ?? null;
}

function toggleFromKeyboard(): void {
    if (state.open) {
        closeSearchCommand();
        return;
    }
    const owner = pickKeyboardOwner();
    if (owner) openSearchCommand(owner);
}

let shortcutListenerInstalled = false;
/** Listener global ÚNICO de Ctrl/Cmd+K y "/"; lo instala la primera
    instancia montada y sobrevive a desmontajes (vive en el módulo). */
export function ensureSearchCommandShortcutListener(): void {
    if (shortcutListenerInstalled || typeof window === "undefined") return;
    shortcutListenerInstalled = true;
    window.addEventListener("keydown", (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            toggleFromKeyboard();
            return;
        }
        if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
            const target = event.target as HTMLElement | null;
            const tag = target?.tagName;
            if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
            event.preventDefault();
            if (!state.open) {
                const owner = pickKeyboardOwner();
                if (owner) openSearchCommand(owner);
            }
        }
    });
}
