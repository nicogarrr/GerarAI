import type { BetterAuthOptions } from 'better-auth';

type RateLimitEnv = Partial<Record<'NODE_ENV' | 'APP_ENV' | 'AUTH_RATE_LIMIT_ENABLED', string | undefined>>;

/**
 * Limites de Better Auth (login, reset, 2FA...).
 *
 * El almacen por defecto de Better Auth es un Map en memoria del proceso. En
 * Vercel cada instancia de la funcion tiene el suyo y se vacia en cada arranque
 * en frio o despliegue, asi que "3 intentos de login cada 10 s por IP" se
 * multiplicaba por el numero de instancias vivas. Con base de datos (la misma
 * MongoDB de las sesiones, coleccion `rateLimit`) el contador es comun a todas.
 * Sin base de datos (solo la instancia de build) se queda en memoria.
 */
export function buildAuthRateLimit(
    { hasDatabase, env }: { hasDatabase: boolean; env: RateLimitEnv },
): NonNullable<BetterAuthOptions['rateLimit']> {
    return {
        enabled: env.NODE_ENV === 'production'
            || env.APP_ENV === 'production'
            || env.AUTH_RATE_LIMIT_ENABLED === 'true',
        storage: hasDatabase ? 'database' : 'memory',
        window: 60,
        max: 100,
        customRules: {
            '/request-password-reset': { window: 60, max: 3 },
            '/reset-password': { window: 60, max: 5 },
            '/change-password': { window: 10, max: 3 },
            '/verify-password': { window: 60, max: 10 },
            '/delete-user': { window: 60, max: 3 },
        },
    };
}
