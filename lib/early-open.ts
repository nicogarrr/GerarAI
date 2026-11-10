/** Retiene los clics sobre HTML visible antes de hidratar los onClick.
 * El layout sirve este script con nonce antes de los gatillos. Cada gatillo
 * se marca al montar; desde entonces React es el único dueño del clic.
 * Se detiene la propagación temprana para evitar la reproducción de React.
 * Los consumidores borran la intención al abrir, nunca en la próxima ruta.
 */
import { OPEN_BRAIN_PENDING_KEY } from '@/lib/brain/open-brain';

/** Marca de apertura pendiente del menú móvil (no la consume nadie más). */
export const EARLY_OPEN_NAV_KEY = 'gerarai:open-nav:pending';

/** Atributo que marca un gatillo cubierto por la captura pre-hidratación. */
export const EARLY_OPEN_ATTR = 'data-early-open';

/** Detalle opcional del gatillo (JSON ya escapado por React al pintar). */
export const EARLY_OPEN_DETAIL_ATTR = 'data-early-open-detail';

/**
 * Fuente única del script inline: se evalúa tal cual en jsdom en los tests,
 * así lo probado es exactamente lo que se sirve en el HTML. Sin imports ni
 * sintaxis moderna: tiene que correr en el primer tick del documento.
 */
export const EARLY_OPEN_CAPTURE_JS = `(function(){
    document.addEventListener('click', function (event) {
        var target = event.target;
        var trigger = target && target.closest ? target.closest('[${EARLY_OPEN_ATTR}]') : null;
        if (!trigger) return;
        // Gatillo ya hidratado: React atiende el clic; escribir la marca
        // abriria el panel DOS veces (o una, en la siguiente navegacion).
        if (trigger.closest('[data-hydrated="1"]')) return;
        var kind = trigger.getAttribute('${EARLY_OPEN_ATTR}');
        if (kind !== 'brain' && kind !== 'mobile-nav') return;
        // Este clic ya tiene dueño: no dejar que React lo reproduzca además
        // cuando hidrate su raíz. El siguiente clic hidratado sí llega a React.
        // preventDefault frena el submit nativo de un formulario aún sin
        // onSubmit hidratado (BrainAskForm): la página no recarga y la
        // apertura retenida ocurre aquí mismo.
        event.stopPropagation();
        event.preventDefault();
        if (kind === 'brain') {
            // El detalle (ticker, pregunta, revisión) viaja en el propio
            // gatillo: el HTML del servidor ya lo conoce. Solo objetos JSON
            // válidos; cualquier otra cosa abre sin detalle.
            var detail = trigger.getAttribute('${EARLY_OPEN_DETAIL_ATTR}');
            var parsed = null;
            if (detail) {
                try {
                    var candidate = JSON.parse(detail);
                    if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) parsed = candidate;
                } catch (err) {}
            }
            // GlobalBrain ya hidratado: va por evento directo; si no, handoff
            // en sessionStorage (lo recoge al montar). Nunca los dos a la vez.
            if (document.documentElement.hasAttribute('data-brain-ready')) {
                window.dispatchEvent(new CustomEvent('gerarai:open-brain', { detail: parsed }));
                return;
            }
            try { window.sessionStorage.setItem(${JSON.stringify(OPEN_BRAIN_PENDING_KEY)}, JSON.stringify(parsed)); } catch (err) {}
        } else if (kind === 'mobile-nav') {
            try { window.sessionStorage.setItem(${JSON.stringify(EARLY_OPEN_NAV_KEY)}, '1'); } catch (err) {}
            // sessionStorage bloqueado: el usuario reintenta ya hidratado.
        }
    }, true);
})();`;

/** Callback-ref que marca un gatillo como hidratado al hacer commit React. */
export function markEarlyOpenHydrated(el: Element | null): void {
    el?.setAttribute('data-hydrated', '1');
}

/** Lee y borra la marca de apertura pendiente del menú móvil (una sola vez). */
export function consumeEarlyNavOpen(): boolean {
    if (typeof window === 'undefined') return false;
    try {
        if (window.sessionStorage.getItem(EARLY_OPEN_NAV_KEY)) {
            window.sessionStorage.removeItem(EARLY_OPEN_NAV_KEY);
            return true;
        }
    } catch {
        // sessionStorage bloqueado: nada que consumir.
    }
    return false;
}
