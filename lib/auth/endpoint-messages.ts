import type { TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';

/**
 * Texto del error de acceso (lib/auth/endpoint.ts) en el idioma elegido.
 * El endpoint solo devuelve códigos documentados; aquí se elige la copia por
 * código y estado, nunca por el texto del upstream. En español sale lo mismo
 * que antes (mismas frases en auth.endpointErrors.*).
 */
const CODE_KEYS: Record<string, TranslationKey> = {
    AUTH_UNAVAILABLE: 'auth.endpointErrors.unavailable',
    AUTH_ENDPOINT_USER_ALREADY_EXISTS: 'auth.endpointErrors.emailTaken',
    AUTH_ENDPOINT_USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL: 'auth.endpointErrors.emailTaken',
    AUTH_ENDPOINT_PASSWORD_TOO_SHORT: 'auth.endpointErrors.passwordTooShort',
    AUTH_ENDPOINT_PASSWORD_TOO_LONG: 'auth.endpointErrors.passwordTooLong',
    AUTH_ENDPOINT_INVALID_EMAIL: 'auth.endpointErrors.invalidEmail',
    AUTH_ENDPOINT_ACCOUNT_PENDING: 'auth.endpointErrors.accountPending',
    AUTH_ENDPOINT_ACCOUNT_REJECTED: 'auth.endpointErrors.accountRejected',
    AUTH_ENDPOINT_SIGNUP_NOT_INVITED: 'auth.endpointErrors.notInvited',
};

const STATUS_KEYS: Record<number, TranslationKey> = {
    429: 'auth.endpointErrors.tooManyAttempts',
    401: 'auth.endpointErrors.invalidCredentials',
    403: 'auth.endpointErrors.notAuthorized',
};

export function authEndpointErrorMessage(
    error: { code: string; statusCode: number },
    t: TranslateFn,
    fallback: string,
): string {
    const key = CODE_KEYS[error.code]
        ?? (error.code === 'AUTH_ENDPOINT_ERROR' ? STATUS_KEYS[error.statusCode] ?? 'auth.endpointErrors.generic' : undefined);
    return key ? t(key) : fallback;
}
