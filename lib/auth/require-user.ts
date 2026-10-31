import { cache } from 'react';
import { headers } from 'next/headers';

import { getAuth } from '@/lib/better-auth/auth';
import { AppError, AuthenticationError } from '@/lib/types/errors';
import {
  ACCOUNT_PENDING_CODE,
  ACCOUNT_PENDING_MESSAGE,
  ACCOUNT_REJECTED_CODE,
  ACCOUNT_REJECTED_MESSAGE,
  isAccountActive,
  normalizeAccountStatus,
} from '@/lib/auth/account-approval';

export type AuthenticatedUser = {
  id: string;
  email?: string | null;
  name?: string | null;
};

/**
 * Resolución de sesión deduplicada POR PETICIÓN (React cache).
 *
 * Antes cada llamada a `requireAuthenticatedUser` ejecutaba
 * `auth.api.getSession`, que valida la sesión contra MongoDB. Una página
 * como /watchlist la invoca decenas de veces por render (layout, acciones y
 * cada fetch a proveedores vía fetchJSON/research-identity), así que una
 * sola vista provocaba ~100+ lecturas de sesión a Atlas en cadena paralela:
 * era el tramo dominante del tiempo de render de servidor.
 *
 * La sesión es inmutable dentro de la petición: la cookie no cambia durante
 * el render, así que resolverla una vez por petición no altera la semántica.
 * Las mutaciones (server actions invocadas desde cliente) son peticiones
 * independientes y vuelven a validar.
 */
const resolveSessionUser = cache(async (): Promise<AuthenticatedUser> => {
  const auth = await getAuth();
  const session = await auth.api.getSession({ headers: await headers() });
  const user = session?.user;
  if (!user?.id) {
    throw new AuthenticationError('User not authenticated');
  }
  // Gate central de aprobación: una sesión de una cuenta pending/rejected
  // (p.ej. creada antes de un rechazo) no abre la app. Coste cero: la sesión
  // ya está cargada y accountStatus viaja en ella (additionalFields). Las
  // cuentas sin el campo (anteriores a la función) cuentan como aprobadas.
  const rawStatus = (user as { accountStatus?: unknown }).accountStatus;
  if (!isAccountActive(rawStatus)) {
    const status = normalizeAccountStatus(rawStatus);
    throw new AppError(
      status === 'rejected' ? ACCOUNT_REJECTED_MESSAGE : ACCOUNT_PENDING_MESSAGE,
      status === 'rejected' ? ACCOUNT_REJECTED_CODE : ACCOUNT_PENDING_CODE,
      403,
    );
  }
  return { id: user.id, email: user.email, name: user.name };
});

/** Resolve identity server-side; caller-supplied user IDs are never trusted. */
export async function requireAuthenticatedUser(): Promise<AuthenticatedUser> {
  // P1: el bypass E2E exigía solo NODE_ENV!=production. Si un contenedor prod
  // arranca con NODE_ENV=development por error, el bypass se activaba.
  // Ahora exige además APP_ENV=test (o E2E_AUTH_SECRET coincidente).
  // El bypass exige APP_ENV=test de forma estricta. Un E2E_AUTH_SECRET
  // cualquiera NO vale: antes bastaba con que la variable existiera, asi que
  // cualquier despliegue con un secreto arbitrario dejaba la auth abierta.
  if (
    process.env.E2E_AUTH_BYPASS === '1' &&
    process.env.NODE_ENV !== 'production' &&
    process.env.APP_ENV === 'test'
  ) {
    return { id: 'e2e-browser-user', email: 'browser@gerarai.test', name: 'Browser Analyst' };
  }
  return resolveSessionUser();
}
