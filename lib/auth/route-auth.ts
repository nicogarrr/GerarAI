// Ruta relativa con .ts a proposito: se importa desde tests con node --test.
// @ts-expect-error TS5097
import { AppError, AuthenticationError } from '../types/errors.ts';

/**
 * Los route handlers que exigen sesion lanzaban AuthenticationError fuera de un
 * try/catch y el cliente recibia un 500. Este envoltorio lo devuelve como 401
 * JSON sin tocar el resto de errores (esos siguen propagandose).
 */
export function withAuthErrors<A extends unknown[]>(
    handler: (...args: A) => Promise<Response>,
): (...args: A) => Promise<Response> {
    return async (...args: A) => {
        try {
            return await handler(...args);
        } catch (error) {
            // Cuenta pendiente/rechazada con sesión: 403 con el código
            // estable del contrato, nunca un 500.
            if (
                error instanceof AppError
                && (error.code === 'ACCOUNT_PENDING' || error.code === 'ACCOUNT_REJECTED')
            ) {
                return Response.json(
                    { error: error.message, code: error.code },
                    { status: 403, headers: { 'Cache-Control': 'no-store' } },
                );
            }
            if (error instanceof AuthenticationError) {
                return Response.json(
                    { error: 'No autenticado' },
                    { status: 401, headers: { 'Cache-Control': 'no-store' } },
                );
            }
            throw error;
        }
    };
}
