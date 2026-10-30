import { cookies, headers } from 'next/headers';
import type { BetterAuthOptions } from 'better-auth';
import { parseSetCookieHeader, toCookieOptions } from 'better-auth/cookies';
import { getAuth } from '@/lib/better-auth/auth';
import { AppError } from '@/lib/types/errors';
import { SIGNUP_NOT_INVITED_CODE, SIGNUP_NOT_INVITED_MESSAGE } from '@/lib/auth/signup-policy';

type AuthEndpoint =
    | '/sign-in/email'
    | '/sign-up/email'
    | '/two-factor/verify-totp'
    | '/request-password-reset'
    | '/reset-password'
    | '/change-password'
    | '/verify-password'
    | '/delete-user';

/** Use the official HTTP pipeline, including its existing rate limits/CSRF.
 * Unlike direct auth.api calls, router calls do not run nextCookies' bridge,
 * so forward their Set-Cookie values explicitly, including expired cookies.
 * No custom IP trust or rate policy is introduced here; the counters live in
 * the shared database (lib/better-auth/rate-limit.ts), not per process.
 */
export async function callAuthEndpoint(
    path: AuthEndpoint,
    body: unknown,
    extraHeaders: Record<string, string> = {},
): Promise<{ twoFactorRedirect?: boolean }> {
    const auth = await getAuth();
    const context = await auth.$context;
    const incoming = await headers();
    const forwarded = new Headers();
    // Keep Origin as supplied so the official CSRF check can reject it. The
    // configured baseURL, never inbound Host/X-Forwarded-Host, sets the target.
    const ipHeaders = (context.options as BetterAuthOptions).advanced?.ipAddress?.ipAddressHeaders ?? ['x-forwarded-for'];
    for (const name of ['cookie', 'origin', 'referer', 'user-agent', 'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest', ...ipHeaders]) {
        const value = incoming.get(name);
        if (value !== null) forwarded.set(name, value);
    }
    forwarded.set('content-type', 'application/json');
    for (const [name, value] of Object.entries(extraHeaders)) {
        forwarded.set(name, value);
    }
    let response: Response;
    try {
        response = await auth.handler(new Request(`${context.baseURL.replace(/\/$/, '')}${path}`, {
            method: 'POST', headers: forwarded, body: JSON.stringify(body),
        }));
    } catch {
        // A failing rate-limit store can reject the handler before a response.
        // Do not retry via auth.api or expose its internal exception.
        throw new AppError('El servicio de acceso no está disponible. Inténtalo más tarde.', 'AUTH_UNAVAILABLE', 503);
    }
    const setCookie = response.headers.get('set-cookie');
    if (setCookie) {
        const store = await cookies();
        for (const [name, attributes] of parseSetCookieHeader(setCookie)) {
            store.set(name, attributes.value, toCookieOptions(attributes));
        }
    }
    if (!response.ok) {
        // Only documented codes select copy. Never expose upstream message,
        // stack or arbitrary fields, and never equate every 422 with duplicate.
        const detail: unknown = await response.json().catch(() => null);
        const code = detail && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string'
            ? detail.code : '';
        const signupMessages: Record<string, string> = {
            USER_ALREADY_EXISTS: 'Este email ya está registrado. Inicia sesión.',
            USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL: 'Este email ya está registrado. Inicia sesión.',
            PASSWORD_TOO_SHORT: 'La contraseña debe tener al menos 8 caracteres.',
            PASSWORD_TOO_LONG: 'La contraseña no puede superar los 128 caracteres.',
            INVALID_EMAIL: 'Introduce un email válido.',
        };
        const signupMessage = path === '/sign-up/email' && (response.status === 400 || response.status === 422)
            ? signupMessages[code] : undefined;
        if (signupMessage) throw new AppError(signupMessage, `AUTH_ENDPOINT_${code}`, response.status);
        // Registro cerrado con lista de invitados: email fuera de SIGNUP_ALLOWLIST.
        if (path === '/sign-up/email' && response.status === 403 && code === SIGNUP_NOT_INVITED_CODE) {
            throw new AppError(SIGNUP_NOT_INVITED_MESSAGE, `AUTH_ENDPOINT_${code}`, response.status);
        }
        const message = response.status === 429
            ? 'Demasiados intentos. Espera un momento antes de volver a intentarlo.'
            : response.status === 401
                ? 'Email o contraseña no válidos. Revisa los datos e inténtalo de nuevo.'
                : response.status === 403
                    ? 'No se ha autorizado esta solicitud de acceso.'
                    : 'No se pudo completar el acceso. Inténtalo de nuevo.';
        throw new AppError(message, 'AUTH_ENDPOINT_ERROR', response.status);
    }
    // Never let the router's raw session token escape to a Server Action.
    const result: unknown = await response.json();
    return { twoFactorRedirect: Boolean(result && typeof result === 'object' && 'twoFactorRedirect' in result && result.twoFactorRedirect) };
}
