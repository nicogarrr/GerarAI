/**
 * Mensaje del resultado de POST extract-candidates-from-registry, puro y
 * ejecutable en tests: 0 creados NUNCA se celebra y el outcome dice la
 * razón real (fuente sin cambios, sin candidatos detectados, sesión no
 * identificada). Ninguno afirma ausencia de compromisos.
 */
export type ExtractFromRegistryResult = { outcome?: string; created?: number; candidates?: unknown[] };

export function extractOutcomeMessage(result: ExtractFromRegistryResult | null | undefined): { message: string; tone?: 'neutral' } {
    const outcome = typeof result?.outcome === 'string' ? result.outcome : '';
    if (outcome === 'sin_contexto_de_tenant') {
        return { message: 'No se pudo identificar tu sesión; vuelve a entrar.', tone: 'neutral' };
    }
    const n = typeof result?.created === 'number' ? result.created : (Array.isArray(result?.candidates) ? result.candidates.length : 0);
    if (n > 0) {
        return { message: `${n} ${n === 1 ? 'candidato nuevo extraído' : 'candidatos nuevos extraídos'} (sin revisar).` };
    }
    if (outcome === 'sin_cambios_hash') {
        return { message: 'No se han añadido candidatos nuevos: la fuente no ha cambiado desde la última extracción.', tone: 'neutral' };
    }
    if (outcome === 'sin_candidatos_detectados') {
        return { message: 'No se detectaron candidatos en esta fuente. Esto no significa que no haya compromisos.', tone: 'neutral' };
    }
    return { message: 'No se han añadido candidatos nuevos.', tone: 'neutral' };
}
