/**
 * Clave de mensaje genérico por categoría para estados de sección caídos.
 * El error crudo (rutas internas, detalles de red, fragments de respuesta,
 * URLs firmadas) nunca llega al usuario. El texto lo resuelve el llamador
 * con t() en el idioma activo (ui.sectionError.*).
 */
import type { TranslationKey } from '@/lib/i18n/messages';

export function sectionErrorKey(error: unknown): TranslationKey {
    const message = error instanceof Error ? error.message : '';
    if (/fetch|network|econn|timeout|timed out|abort/i.test(message)) {
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
