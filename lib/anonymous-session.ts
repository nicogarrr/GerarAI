/** Solo para shells públicos/auth: sin cookie de sesión de better-auth no
 * existe sesión de navegador que validar. Antes bastaba CUALQUIER cookie
 * (incluida `gerarai_locale`, que pone cualquier visitante al cambiar de
 * idioma) para pagar una validación de sesión contra la base de datos en
 * cada visita anónima a la landing o al shell de auth.
 *
 * El nombre tolera el prefijo `__Secure-` de producción y el troceado
 * (`session_token.0`, `session_token.1`) de cookies grandes.
 * No sustituye requireAuthenticatedUser ni autoriza acceso privado.
 */
const SESSION_COOKIE_NAME = /better-auth\..*session/;

export async function readSessionWhenCookies<T>(
  requestHeaders: Pick<Headers, 'get'>,
  readSession: () => Promise<T>,
): Promise<T | null> {
  const header = requestHeaders.get('cookie');
  if (!header?.trim()) return null;
  const hasSessionCookie = header
    .split(';')
    .some((part) => SESSION_COOKIE_NAME.test(part.split('=', 1)[0]?.trim() ?? ''));
  if (!hasSessionCookie) return null;
  return readSession();
}
