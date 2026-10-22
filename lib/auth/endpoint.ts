import { cookies, headers } from 'next/headers';
import type { BetterAuthOptions } from 'better-auth';
import { parseSetCookieHeader, toCookieOptions } from 'better-auth/cookies';
import { getAuth } from '@/lib/better-auth/auth';
import { AppError } from '@/lib/types/errors';

type AuthEndpoint = '/sign-in/email' | '/sign-up/email' | '/two-factor/verify-totp';

/** Use the official HTTP pipeline, including its existing rate limits/CSRF.
 * Unlike direct auth.api calls, router calls do not run nextCookies' bridge,
 * so forward their Set-Cookie values explicitly, including expired cookies.
 * No custom IP trust, rate policy or persistent storage is introduced here.
 * Existing memory rate limits remain per process, not global across replicas.
 */
export async function callAuthEndpoint(path: AuthEndpoint, body: unknown): Promise<{ twoFactorRedirect?: boolean }> {
    const auth = await getAuth();
    const context = await auth.$context;
    const incoming = await headers();
    const forwarded = new Headers();
    // Keep Origin as supplied so the official CSRF check can reject it. The
    // configured baseURL, never inbound Host/X-Forwarded-Host, sets the target.
    const ipHeaders = (context.options as BetterAuthOptions).advanced?.ipAddress?.ipAddressHeaders ?? ['x-forwarded-for'];
    for (const name of ['cookie', 'origin', 'referer', 'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest', ...ipHeaders]) {
        const value = incoming.get(name);
        if (value !== null) forwarded.set(name, value);
    }
    forwarded.set('content-type', 'application/json');
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
