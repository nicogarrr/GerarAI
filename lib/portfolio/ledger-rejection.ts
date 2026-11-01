import { createTranslator } from '@/lib/i18n/translate';
import { AppError } from '@/lib/types/errors';

/**
 * Rechazos conocidos del ledger al dar de alta o editar un movimiento.
 *
 * En producción Next oculta el mensaje de cualquier error lanzado desde una
 * server action, así que una venta por encima de lo que tienes acababa como
 * «El motor de análisis no responde» (y en desarrollo, en inglés:
 * «Insufficient shares for sale»). Estos rechazos se devuelven como
 * resultado con el motivo en el idioma elegido (español por defecto) para que el formulario siga abierto.
 * Devuelve null si el error no es un rechazo conocido (se relanza).
 */
export function ledgerRejection(error: unknown, operation: 'save' | 'delete' = 'save', locale: 'es' | 'en' = 'es'): string | null {
    if (!(error instanceof AppError) || error.code !== 'RESEARCH_API_ERROR') return null;
    const t = createTranslator(locale);
    const message = error.message;
    if (error.statusCode === 409 && /insufficient shares/i.test(message)) {
        return operation === 'delete'
            ? t('portfolio.ledgerRejection.deleteInsufficient')
            : t('portfolio.ledgerRejection.sellInsufficient');
    }
    if (error.statusCode === 422 && /mix transaction currencies/i.test(message)) {
        return t('portfolio.ledgerRejection.mixedCurrency');
    }
    if (error.statusCode === 404 && /transaction not found/i.test(message)) {
        return t('portfolio.ledgerRejection.notFound');
    }
    // trade_date llega como 422 con lista pydantic y researchErrorDetail
    // conserva el CAMPO, no el motivo: con el mismo campo fallan la fecha
    // futura (validador del modelo), una fecha imposible ('2026-02-30'),
    // texto no parseable y null (validacion de tipo de Pydantic, antes de
    // cualquier validador). Sin motivo distinguible no se puede afirmar
    // 'futura': mensaje de fecha invalida que cubre todos los casos.
    if (error.statusCode === 422 && /\btrade_date\b/.test(message)) {
        return t('portfolio.ledgerRejection.invalidDate');
    }
    return null;
}
