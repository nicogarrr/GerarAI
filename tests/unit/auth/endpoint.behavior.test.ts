import { beforeEach, describe, expect, it, vi } from 'vitest';

const { handler, getAuth, incomingHeaders, cookieSet } = vi.hoisted(() => ({
    handler: vi.fn(), getAuth: vi.fn(), incomingHeaders: vi.fn(), cookieSet: vi.fn(),
}));
vi.mock('@/lib/better-auth/auth', () => ({ getAuth }));
vi.mock('next/headers', () => ({ headers: incomingHeaders, cookies: async () => ({ set: cookieSet }) }));
vi.mock('@/lib/i18n/server', () => ({ getT: async () => (key: string) => key }));

import { callAuthEndpoint } from '@/lib/auth/endpoint';
import { ACCOUNT_PENDING_CODE, ACCOUNT_PENDING_MESSAGE, ACCOUNT_REJECTED_CODE, ACCOUNT_REJECTED_MESSAGE } from '@/lib/auth/account-approval';
import { SIGNUP_NOT_INVITED_CODE, SIGNUP_NOT_INVITED_MESSAGE } from '@/lib/auth/signup-policy';
import { LEGAL_ACCEPTANCE_REQUIRED_CODE } from '@/lib/auth/legal-acceptance';

const body = { email: 'synthetic@example.invalid', password: 'synthetic-test-input' };
const configure = (options = {}, baseURL = 'https://auth.example.invalid/api/auth/') => {
    getAuth.mockResolvedValue({ $context: Promise.resolve({ baseURL, options }), handler });
};
const respond = (status: number, result: unknown) => {
    handler.mockImplementation(async () => Response.json(result, { status }));
};

beforeEach(() => {
    vi.clearAllMocks();
    handler.mockReset().mockResolvedValue(Response.json({ token: 'synthetic-token-not-for-output' }));
    incomingHeaders.mockResolvedValue(new Headers());
    configure();
});

describe('auth endpoint bridge contracts', () => {
    it('posts JSON only to the configured auth origin, not inbound proxy hosts', async () => {
        incomingHeaders.mockResolvedValue(new Headers({
            origin: 'https://untrusted.example.invalid',
            host: 'untrusted.example.invalid',
            'x-forwarded-host': 'untrusted.example.invalid',
            'user-agent': 'Synthetic Unit Test',
            cookie: 'synthetic=fixture',
            'x-forwarded-for': '203.0.113.12, 203.0.113.13',
            authorization: 'not-forwarded',
            'sec-fetch-site': 'cross-site',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-dest': 'document',
            referer: 'https://untrusted.example.invalid/login',
        }));
        const result = await callAuthEndpoint('/sign-in/email', body);
        expect(result).toEqual({ twoFactorRedirect: false });
        const request = handler.mock.calls[0][0] as Request;
        expect(request.url).toBe('https://auth.example.invalid/api/auth/sign-in/email');
        expect(request.method).toBe('POST');
        expect(await request.json()).toEqual(body);
        expect(request.headers.get('content-type')).toBe('application/json');
        expect(request.headers.get('origin')).toBe('https://untrusted.example.invalid');
        expect(request.headers.get('x-forwarded-for')).toBe('203.0.113.12, 203.0.113.13');
        expect(request.headers.get('cookie')).toBe('synthetic=fixture');
        expect(request.headers.get('user-agent')).toBe('Synthetic Unit Test');
        expect(request.headers.get('sec-fetch-site')).toBe('cross-site');
        expect(request.headers.get('sec-fetch-mode')).toBe('navigate');
        expect(request.headers.get('sec-fetch-dest')).toBe('document');
        expect(request.headers.get('referer')).toBe('https://untrusted.example.invalid/login');
        for (const header of ['host', 'x-forwarded-host', 'authorization']) {
            expect(request.headers.get(header)).toBeNull();
        }
    });

    it('uses configured IP headers and explicit endpoint headers unchanged', async () => {
        configure({ advanced: { ipAddress: { ipAddressHeaders: ['x-real-ip'] } } });
        incomingHeaders.mockResolvedValue(new Headers({ 'x-real-ip': '203.0.113.15', 'x-forwarded-for': '203.0.113.16' }));
        await callAuthEndpoint('/verify-password', body, { 'x-test-purpose': 'synthetic-unit' });
        const request = handler.mock.calls[0][0] as Request;
        expect(request.headers.get('x-real-ip')).toBe('203.0.113.15');
        expect(request.headers.get('x-forwarded-for')).toBeNull();
        expect(request.headers.get('x-test-purpose')).toBe('synthetic-unit');
    });

    it('forwards session cookie attributes and expired cookie deletions', async () => {
        const headers = new Headers();
        headers.append('set-cookie', 'synthetic-session=unit-value; Path=/; HttpOnly; Secure; SameSite=Lax');
        headers.append('set-cookie', 'synthetic-pending=; Path=/; Max-Age=0; HttpOnly');
        handler.mockResolvedValue(Response.json({ twoFactorRedirect: true, token: 'synthetic-private' }, { headers }));
        expect(await callAuthEndpoint('/two-factor/verify-totp', { code: '123456' })).toEqual({ twoFactorRedirect: true });
        expect(cookieSet).toHaveBeenCalledWith('synthetic-session', 'unit-value', expect.objectContaining({ httpOnly: true, secure: true, sameSite: 'lax', path: '/' }));
        expect(cookieSet).toHaveBeenCalledWith('synthetic-pending', '', expect.objectContaining({ maxAge: 0, httpOnly: true }));
    });

    it('fails closed with a safe 503 when the auth handler throws', async () => {
        handler.mockRejectedValue(new Error('synthetic private store detail'));
        await expect(callAuthEndpoint('/sign-in/email', body)).rejects.toMatchObject({
            code: 'AUTH_UNAVAILABLE', statusCode: 503,
            message: 'El servicio de acceso no está disponible. Inténtalo más tarde.',
        });
        expect(handler).toHaveBeenCalledTimes(1);
        expect(cookieSet).not.toHaveBeenCalled();
    });

    it.each([
        [429, 'Demasiados intentos. Espera un momento antes de volver a intentarlo.'],
        [401, 'Email o contraseña no válidos. Revisa los datos e inténtalo de nuevo.'],
        [403, 'No se ha autorizado esta solicitud de acceso.'],
        [500, 'No se pudo completar el acceso. Inténtalo de nuevo.'],
    ])('keeps status %s and never exposes arbitrary upstream copy', async (status, message) => {
        respond(status, { code: 'UNKNOWN', message: 'synthetic upstream private detail' });
        await expect(callAuthEndpoint('/sign-in/email', body)).rejects.toMatchObject({ code: 'AUTH_ENDPOINT_ERROR', statusCode: status, message });
    });

    it.each([
        ['USER_ALREADY_EXISTS', 'Este email ya está registrado. Inicia sesión.'],
        ['USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL', 'Este email ya está registrado. Inicia sesión.'],
        ['PASSWORD_TOO_SHORT', 'La contraseña debe tener al menos 8 caracteres.'],
        ['PASSWORD_TOO_LONG', 'La contraseña no puede superar los 128 caracteres.'],
        ['INVALID_EMAIL', 'Introduce un email válido.'],
        [LEGAL_ACCEPTANCE_REQUIRED_CODE, 'auth.signUp.acceptTermsRequired'],
    ])('maps the documented signup code %s', async (code, message) => {
        respond(422, { code });
        await expect(callAuthEndpoint('/sign-up/email', body)).rejects.toMatchObject({ code: `AUTH_ENDPOINT_${code}`, statusCode: 422, message });
    });

    it.each([ACCOUNT_PENDING_CODE, ACCOUNT_REJECTED_CODE])('distinguishes account status %s from invalid credentials', async (code) => {
        respond(403, { code });
        await expect(callAuthEndpoint('/sign-in/email', body)).rejects.toMatchObject({
            code: `AUTH_ENDPOINT_${code}`, statusCode: 403,
            message: code === ACCOUNT_PENDING_CODE ? ACCOUNT_PENDING_MESSAGE : ACCOUNT_REJECTED_MESSAGE,
        });
    });

    it('preserves closed-signup copy only for the documented 403 code', async () => {
        respond(403, { code: SIGNUP_NOT_INVITED_CODE });
        await expect(callAuthEndpoint('/sign-up/email', body)).rejects.toMatchObject({ message: SIGNUP_NOT_INVITED_MESSAGE, code: `AUTH_ENDPOINT_${SIGNUP_NOT_INVITED_CODE}` });
    });

    it.each([null, 'private string', { code: 42 }, { message: 'unknown 422' }])('does not turn every 422 into a duplicate-email error: %j', async (detail) => {
        respond(422, detail);
        await expect(callAuthEndpoint('/sign-up/email', body)).rejects.toMatchObject({
            code: 'AUTH_ENDPOINT_ERROR', message: 'No se pudo completar el acceso. Inténtalo de nuevo.',
        });
    });

    it('sanitizes a non-JSON failure response', async () => {
        handler.mockResolvedValue(new Response('synthetic upstream HTML', { status: 502 }));
        await expect(callAuthEndpoint('/sign-in/email', body)).rejects.toMatchObject({ code: 'AUTH_ENDPOINT_ERROR', statusCode: 502 });
    });

    it('returns signup account status but strips raw tokens, user and arbitrary fields', async () => {
        respond(200, { token: 'synthetic-private-token', user: { accountStatus: 'pending', email: body.email }, extra: 'private' });
        expect(await callAuthEndpoint('/sign-up/email', body)).toEqual({ twoFactorRedirect: false, accountStatus: 'pending' });
        expect(await callAuthEndpoint('/sign-in/email', body)).toEqual({ twoFactorRedirect: false });
    });

    it.each([null, 'ok', { user: { accountStatus: 123 } }, { user: null }])('does not invent account status from %j', async (result) => {
        respond(200, result);
        expect(await callAuthEndpoint('/sign-up/email', body)).toEqual({ twoFactorRedirect: false });
    });
});
