/**
 * Clave de mensaje genérico por categoría para estados de sección caídos.
 * El error crudo (rutas internas, detalles de red, fragments de respuesta,
 * URLs firmadas) nunca llega al usuario. El texto lo resuelve el llamador
 * con t() en el idioma activo (ui.sectionError.*).
 */
import type { TranslationKey } from '@/lib/i18n/messages';

export function sectionErrorKey(error: unknown): TranslationKey {
    // DOMException (TimeoutError/AbortError de AbortSignal.timeout) no
    // extiende Error: message y name se leen de forma estructural.
    const carrier = error as { message?: unknown; name?: unknown } | null;
    const message = typeof carrier?.message === 'string' ? carrier.message : '';
    const name = typeof carrier?.name === 'string' ? carrier.name : '';
    // Un timeout del backend no es «sin conexión»: el servicio existe pero
    // tardó demasiado. Se distingue para no culpar a la red del usuario.
    if (/timeout|timed out|abort/i.test(message) || name === 'TimeoutError' || name === 'AbortError') {
        return 'ui.sectionError.timeout';
    }
    if (/fetch|network|econn/i.test(message)) {
        return 'ui.sectionError.network';
    }
    if (/401|403|unauthor|forbidden|sesion|session/i.test(message)) {
        return 'ui.sectionError.session';
    }
    if (/5\d\d|server|interno|internal/i.test(message)) {
        return 'ui.sectionError.server';
    }
    return 'ui.sectionError.generic';
}
