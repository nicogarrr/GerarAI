/**
 * Aviso del motor de valoración (trace.notice) en el idioma de la UI.
 *
 * Los motores guardan la traza técnica en inglés (data-engine/app/valuation/
 * engines/base.py y pre_revenue.py); el memo la traduce en
 * thesis_service._notice_es, pero la ficha interpolaba el literal crudo bajo
 * una etiqueta en español («Nota del motor: INDICATIVE RANGE — ...»). Mismo
 * criterio que lib/research/backend-error-es.ts: el literal del wire se
 * traduce en el borde de UI por prefijo estable, y lo desconocido pasa tal
 * cual (los avisos ya emitidos en español, p. ej. el de comparables
 * sectoriales de valuation_service.py, no se tocan).
 */
export function engineNoticeText(notice: string, locale: 'es' | 'en' = 'es'): string {
    if (locale === 'en') return notice;
    if (notice.startsWith('INDICATIVE RANGE')) {
        return 'RANGO INDICATIVO: usa un margen FCF supuesto porque no hay un balance coherente. No es un valor justo final; resuelve los inputs que faltan antes de publicar.';
    }
    if (notice.startsWith('Valuation computed')) {
        return 'Valoración calculada con inputs que no se pueden rastrear hasta una fuente fechada: las cifras son una orientación, no una valoración final.';
    }
    return notice;
}
