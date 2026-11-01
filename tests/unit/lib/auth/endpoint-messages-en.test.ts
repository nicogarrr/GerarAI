import { describe, expect, it } from 'vitest';
import { authEndpointErrorMessage } from '@/lib/auth/endpoint-messages';
import { createTranslator } from '@/lib/i18n/translate';
import { ACCOUNT_PENDING_MESSAGE, ACCOUNT_REJECTED_MESSAGE } from '@/lib/auth/account-approval';
import { SIGNUP_NOT_INVITED_MESSAGE } from '@/lib/auth/signup-policy';

const err = (code: string, statusCode: number) => ({ code, statusCode });

describe('authEndpointErrorMessage', () => {
    it('en inglés: copia por código y estado, nunca el texto del upstream', () => {
        const t = createTranslator('en');
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_USER_ALREADY_EXISTS', 422), t, 'x')).toBe('This email is already registered. Sign in instead.');
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_PASSWORD_TOO_SHORT', 400), t, 'x')).toBe('Password must be at least 8 characters.');
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_ACCOUNT_PENDING', 403), t, 'x')).toMatch(/pending approval/);
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_SIGNUP_NOT_INVITED', 403), t, 'x')).toMatch(/invite list/);
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_ERROR', 429), t, 'x')).toBe('Too many attempts. Wait a moment before trying again.');
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_ERROR', 401), t, 'x')).toBe('Invalid email or password. Check the details and try again.');
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_ERROR', 500), t, 'x')).toBe("We couldn't complete the sign-in. Try again.");
        expect(authEndpointErrorMessage(err('AUTH_UNAVAILABLE', 503), t, 'x')).toMatch(/isn't available/);
    });
    it('código desconocido: devuelve el texto seguro de siempre', () => {
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_SOMETHING_NEW', 400), createTranslator('en'), 'fallback')).toBe('fallback');
    });
    it('en español: las mismas frases que el endpoint', () => {
        const t = createTranslator('es');
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_ACCOUNT_PENDING', 403), t, 'x')).toBe(ACCOUNT_PENDING_MESSAGE);
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_ACCOUNT_REJECTED', 403), t, 'x')).toBe(ACCOUNT_REJECTED_MESSAGE);
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_SIGNUP_NOT_INVITED', 403), t, 'x')).toBe(SIGNUP_NOT_INVITED_MESSAGE);
        expect(authEndpointErrorMessage(err('AUTH_ENDPOINT_ERROR', 403), t, 'x')).toBe('No se ha autorizado esta solicitud de acceso.');
    });
});
