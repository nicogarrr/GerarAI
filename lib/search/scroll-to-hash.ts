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
 * Tres estados por tick (auditoría #2046: la URL tarda en comprometerse):
 *  1. current === wanted → navegación comprometida: scroll cuando el
 *     elemento exista (puede tardar en renderizarse en navegación cruzada).
 *  2. current === pendingFrom (el hash que había al invocar) → el push aún
 *     no compromete: seguir esperando dentro de la ventana.
 *  3. cualquier OTRO valor → el usuario navegó a otra cosa: abortar sin
 *     secuestrar su scroll.
 * La ventana es corta y acotada (~1,5 s); al agotarse, se para en silencio.
 * Sin dependencias de React ni de Next: puro e inyectable para node.
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
    /** Ritmo de reintento; por defecto RETRY_INTERVAL_MS. */
    intervalMs?: number;
    /** Reintentos máximos; por defecto MAX_ATTEMPTS. */
    maxAttempts?: number;
}

/** Normaliza un hash de URL para compararlo con un id ya decodificado. */
function normalizeHash(raw: string): string {
    const value = raw.startsWith('#') ? raw.slice(1) : raw;
    try {
        return decodeURIComponent(value);
    } catch {
        return value;
    }
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
 * Desplaza la vista al elemento con ese id cuando la URL comprometa el hash
 * y el elemento exista. `hash` es el id YA decodificado (de hashFromHref);
 * la comparación normaliza ambos lados por igual.
 */
export function scrollToHashAnchor(hash: string, deps: ScrollToHashDeps = {}): void {
    const getElementById = deps.getElementById ?? ((id: string) => document.getElementById(id));
    const getCurrentHash = deps.getCurrentHash ?? (() => window.location.hash);
    const setTimeoutFn = deps.setTimeoutFn ?? ((callback: () => void, ms: number) => { setTimeout(callback, ms); });
    // La ventana por defecto (~1,5 s) cubre la navegación interna; quien
    // llega a una página servida por Suspense (ancla en la URL inicial)
    // necesita una ventana más larga: la pasa por parámetro.
    const intervalMs = deps.intervalMs ?? RETRY_INTERVAL_MS;
    const maxAttempts = deps.maxAttempts ?? MAX_ATTEMPTS;
    // Hash visible al invocar, ANTES de que router.push comprometa la nueva
    // URL: mientras la barra siga en él, la navegación sigue pendiente.
    const pendingFrom = normalizeHash(getCurrentHash());
    let attempts = 0;
    const attempt = () => {
        const current = normalizeHash(getCurrentHash());
        if (current === hash) {
            const element = getElementById(hash);
            if (element) {
                element.scrollIntoView({ block: 'start' });
                // Las secciones Suspense de arriba (gráfico, cotización)
                // pueden resolver DESPUÉS y empujar el ancla: una segunda
                // pasada absorbe ese layout shift si el hash sigue activo.
                setTimeoutFn(() => {
                    if (normalizeHash(getCurrentHash()) !== hash) return;
                    getElementById(hash)?.scrollIntoView({ block: 'start' });
                }, intervalMs * 4);
                return;
            }
            // Hash comprometido pero el elemento aún no existe: reintentar.
        } else if (current !== pendingFrom) {
            // Tercer hash: el usuario navegó a otra cosa. No secuestrar.
            return;
        }
        // current === pendingFrom: el push aún no compromete; seguir.
        attempts += 1;
        if (attempts < maxAttempts) setTimeoutFn(attempt, intervalMs);
    };
    setTimeoutFn(attempt, 0);
}
