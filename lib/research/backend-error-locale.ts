import { getLocale } from '@/lib/i18n/server';
import { backendMessage } from '@/lib/research/backend-error-es';

/**
 * Server actions: mensaje del motor en el idioma de la petición (cookie de
 * Ajustes → Idioma). Fuera de una petición (tests, scripts) queda en español.
 */
export async function backendMessageForRequest(message: string | null | undefined): Promise<string> {
    let locale: 'es' | 'en' = 'es';
    try {
        locale = await getLocale();
    } catch {
        // Sin contexto de petición: español por defecto.
    }
    return backendMessage(message, locale);
}
