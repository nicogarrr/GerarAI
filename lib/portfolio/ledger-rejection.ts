import { AppError } from '@/lib/types/errors';

/**
 * Rechazos conocidos del ledger al dar de alta o editar un movimiento.
 *
 * En producción Next oculta el mensaje de cualquier error lanzado desde una
 * server action, así que una venta por encima de lo que tienes acababa como
 * «El motor de análisis no responde» (y en desarrollo, en inglés:
 * «Insufficient shares for sale»). Estos rechazos se devuelven como
 * resultado con el motivo en español para que el formulario siga abierto.
 * Devuelve null si el error no es un rechazo conocido (se relanza).
 */
export function ledgerRejection(error: unknown, operation: 'save' | 'delete' = 'save'): string | null {
    if (!(error instanceof AppError) || error.code !== 'RESEARCH_API_ERROR') return null;
    const message = error.message;
    if (error.statusCode === 409 && /insufficient shares/i.test(message)) {
        return operation === 'delete'
            ? 'No se puede borrar: una venta posterior se quedaría sin acciones. Borra o corrige antes esa venta.'
            : 'No puedes vender más acciones de las que tienes en cartera. Revisa la cantidad o registra antes la compra.';
    }
    if (error.statusCode === 422 && /mix transaction currencies/i.test(message)) {
        return 'Esta posición ya tiene movimientos en otra divisa: registra este en la misma divisa que los anteriores.';
    }
    if (error.statusCode === 404 && /transaction not found/i.test(message)) {
        return 'Ese movimiento ya no existe (quizá se borró en otra pestaña). Recarga la página.';
    }
    return null;
}
