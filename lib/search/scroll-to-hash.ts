/**
 * Scroll al ancla de un href con `#hash` tras `router.push`.
 *
 * Bug (22-oct-2026, prod): en la ficha /research/MSFT, con la página
 * desplazada abajo, el comando de la paleta «MSFT GP» (o «MSFT ALERT»)
 * fijaba location.hash pero la vista NO se movía al ancla (#grafico quedaba
 * a -3155 px del viewport). El App Router no hace scroll al ancla en
 * `router.push` cuando la ruta no cambia; al ser la paleta quien construye
 * la URL, el scroll es responsabilidad del llamador.
 *
 * Reintentos durante una ventana corta (~1,5 s): en navegación cruzada el
 * destino puede tardar en renderizarse. Se aborta si el hash de la URL
 * cambia (el usuario navegó a otra cosa mientras tanto). Sin dependencias
 * de React ni de Next: puro e inyectable para probarlo en node.
 */

const RETRY_INTERVAL_MS = 100;
const MAX_ATTEMPTS = 15;

interface ScrollTarget {
    scrollIntoView: (options?: { block?: 'start' | 'center' | 'end' | 'nearest' }) => void;
}

interface ScrollToHashDeps {
    getElementById?: (id: string) => ScrollTarget | null;
    getCurrentHash?: () => string;
    setTimeoutFn?: (callback: () => void, ms: number) => void;
}

/** Extrae el ancla de un href (`/ruta?v=1#ancla` → `ancla`); null si no hay. */
export function hashFromHref(href: string): string | null {
    const index = href.indexOf('#');
    if (index < 0 || index === href.length - 1) return null;
    const raw = href.slice(index + 1);
    try {
        return decodeURIComponent(raw);
    } catch {
        return raw;
    }
}

/**
 * Desplaza la vista al elemento con ese id cuando exista. Si aún no existe
 * (navegación cruzada en curso), reintenta hasta agotar la ventana. Si el
 * hash actual deja de coincidir, no hace nada más.
 */
export function scrollToHashAnchor(hash: string, deps: ScrollToHashDeps = {}): void {
    const getElementById = deps.getElementById ?? ((id: string) => document.getElementById(id));
    const getCurrentHash = deps.getCurrentHash ?? (() => window.location.hash);
    const setTimeoutFn = deps.setTimeoutFn ?? ((callback: () => void, ms: number) => { setTimeout(callback, ms); });
    const wanted = `#${hash}`;
    let attempts = 0;
    const attempt = () => {
        // El usuario navegó a otra cosa: no secuestrar su scroll.
        if (getCurrentHash() !== wanted) return;
        const element = getElementById(hash);
        if (element) {
            element.scrollIntoView({ block: 'start' });
            // Las secciones Suspense de arriba (gráfico, cotización) pueden
            // resolver DESPUÉS y empujar el ancla: una segunda pasada
            // absorbe ese layout shift si el hash sigue activo.
            setTimeoutFn(() => {
                if (getCurrentHash() !== wanted) return;
                getElementById(hash)?.scrollIntoView({ block: 'start' });
            }, RETRY_INTERVAL_MS * 4);
            return;
        }
        attempts += 1;
        if (attempts < MAX_ATTEMPTS) setTimeoutFn(attempt, RETRY_INTERVAL_MS);
    };
    setTimeoutFn(attempt, 0);
}
