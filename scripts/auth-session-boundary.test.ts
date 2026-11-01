/** node --experimental-strip-types --test scripts/auth-session-boundary.test.ts */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { register } from 'node:module';
register('./auth-session-boundary.loader.mjs', import.meta.url);
// @ts-expect-error TS5097: node strip-types needs the real source extension.
const { signInWithEmail, signUpWithEmail, verifyTwoFactorTotp } = await import('../lib/actions/auth.actions.ts');

const credentials = { email: 'synthetic@example.com', password: 'synthetic-password-only' };
const privateResponse = {
    token: 'synthetic-session-canary',
    user: { id: 'synthetic-user', email: credentials.email },
};
const authGlobal = globalThis as typeof globalThis & { __authBoundaryTestAuth: unknown };

test('successful authentication actions never serialize session tokens or user objects', async () => {
    const inputs: unknown[] = [];
    const reply = async (input: unknown) => { inputs.push(input); return privateResponse; };
    authGlobal.__authBoundaryTestAuth = { api: { signInEmail: reply, signUpEmail: reply, verifyTOTP: reply } };
    const results = [
        await signInWithEmail(credentials),
        await signUpWithEmail({ ...credentials, fullName: 'Synthetic', country: 'ES', investmentGoals: 'Growth', riskTolerance: 'Medium', preferredIndustry: 'Technology', acceptTerms: true }),
        await verifyTwoFactorTotp({ ...credentials, totpCode: '123456' }),
    ];
    assert.equal(inputs.length, 3);
    for (const result of results) {
        assert.deepEqual(result, { success: true });
        assert.ok(!JSON.stringify(result).includes(privateResponse.token));
    }
});

test('pending two-factor sign-in is not converted to a successful session', async () => {
    authGlobal.__authBoundaryTestAuth = { api: { signInEmail: async () => ({ twoFactorRedirect: true, ...privateResponse }) } };
    assert.deepEqual(await signInWithEmail(credentials), { success: false, twoFactorRequired: true });
});

// @ts-expect-error TS5097: source extension for node strip-types.
const { AppError } = await import('../lib/types/errors.ts');
test('actions preserve structured endpoint copy instead of guessing from substrings', async () => {
    const errorState = globalThis as typeof globalThis & { __authBoundaryEndpointError?: Error };
    for (const [code, message, status] of [
        ['AUTH_ENDPOINT_USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL', 'Este email ya está registrado. Inicia sesión.', 422],
        ['AUTH_ENDPOINT_ACCOUNT_PENDING', 'Tu cuenta está pendiente de aprobación. Te avisaremos por email cuando esté activa.', 403],
        ['AUTH_ENDPOINT_ACCOUNT_REJECTED', 'Tu solicitud de acceso no fue aprobada.', 403],
        ['AUTH_ENDPOINT_PASSWORD_TOO_SHORT', 'La contraseña debe tener al menos 8 caracteres.', 400],
        ['AUTH_ENDPOINT_ERROR', 'Demasiados intentos. Espera un momento antes de volver a intentarlo.', 429],
        ['AUTH_UNAVAILABLE', 'El servicio de acceso no está disponible. Inténtalo más tarde.', 503],
    ] as const) {
        errorState.__authBoundaryEndpointError = new AppError(message, code, status);
        // El formulario necesita `code` SOLO para abrir la pantalla de cuenta
        // pendiente/rechazada en lugar del toast generico; el resto de errores
        // mantiene la forma exacta de siempre (sin `code`).
        const expectsCode = code === 'AUTH_ENDPOINT_ACCOUNT_PENDING' || code === 'AUTH_ENDPOINT_ACCOUNT_REJECTED';
        const expectedSignIn: Record<string, unknown> = { success: false, error: message };
        if (expectsCode) {
            // Codigo estable hacia el front (no el crudo AUTH_ENDPOINT_*).
            expectedSignIn.code = code === 'AUTH_ENDPOINT_ACCOUNT_PENDING' ? 'ACCOUNT_PENDING' : 'ACCOUNT_REJECTED';
        }
        assert.deepEqual(await signInWithEmail(credentials), expectedSignIn);
        assert.deepEqual(await signUpWithEmail({ ...credentials, fullName: 'Synthetic', country: 'ES', investmentGoals: 'Growth', riskTolerance: 'Medium', preferredIndustry: 'Technology', acceptTerms: true }), { success: false, error: message });
    }
    delete errorState.__authBoundaryEndpointError;
});
