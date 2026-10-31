/**
 * Pantalla de cuenta pendiente: estados que sabe mostrar la interfaz y
 * traduccion de los codigos con los que viaja el estado de aprobacion.
 *
 * Reglas puras, sin red ni base de datos. El contrato (cerrado con el carril
 * de backend, 31-oct-2026):
 * - Alta abierta: /sign-up/email crea la cuenta SIN sesion (autoSignIn=false)
 *   y la respuesta trae `user.accountStatus`; el server action
 *   `signUpWithEmail` lo devuelve como `accountStatus`.
 * - /sign-in/email rechaza con HTTP 403 y code ACCOUNT_PENDING /
 *   ACCOUNT_REJECTED; endpoint.ts los propaga como AppError
 *   `AUTH_ENDPOINT_<code>` y el server action lo devuelve en `code`.
 * - Las sesiones de cuentas pendientes o rechazadas no valen para la app.
 *
 * Este modulo es el unico sitio del front que conoce la escritura de esos
 * codigos: si el backend los renombra, solo cambia aqui.
 */

/** Estado de aprobacion que la respuesta del alta puede traer. */
export type AccountApprovalStatus = 'pending' | 'approved' | 'rejected';

/** Estados que sabe pintar la pantalla de cuenta pendiente. */
export type PendingAccountState = 'pendiente' | 'rechazada';

/**
 * Traduce el `code` que devuelve `signInWithEmail` al estado de la pantalla.
 * Acepta el codigo interno propagado (`AUTH_ENDPOINT_ACCOUNT_PENDING`) y, de
 * forma defensiva, el codigo crudo de la API (`ACCOUNT_PENDING`): si la capa
 * intermedia cambia el prefijo, la pantalla sigue funcionando.
 * Devuelve null para cualquier otro error (credenciales, red...): esos van
 * al toast de siempre.
 */
export function pendingStateFromSignInCode(code: string | undefined): PendingAccountState | null {
    if (!code) return null;
    if (code.endsWith('ACCOUNT_PENDING')) return 'pendiente';
    if (code.endsWith('ACCOUNT_REJECTED')) return 'rechazada';
    return null;
}

/**
 * Decide a donde va el usuario tras un alta con exito. Bajo la politica de
 * aprobacion toda cuenta nueva nace pendiente; un `accountStatus` 'approved'
 * explicito (p. ej. autoaprobacion futura) entra directo y cualquier otro
 * caso (pendiente o campo ausente) va a la pantalla de estado: con
 * autoSignIn=false no hay sesion y mandar a /inicio rebotaria a /sign-in.
 */
export function afterSignUpRoute(accountStatus: unknown): '/inicio' | PendingAccountState {
    if (accountStatus === 'approved') return '/inicio';
    if (accountStatus === 'rejected') return 'rechazada';
    return 'pendiente';
}

/** Ruta de la pantalla de cuenta pendiente para un estado dado. */
export function cuentaPendienteHref(state: PendingAccountState): string {
    return `/cuenta-pendiente?estado=${state}`;
}

/**
 * Estado pedido por querystring (`?estado=`). Cualquier valor desconocido o
 * ausente cae en 'pendiente': es el estado informativo y nunca acusa al
 * usuario de un rechazo que no existe.
 */
export function parsePendingState(raw: unknown): PendingAccountState {
    const value = Array.isArray(raw) ? raw[0] : raw;
    return value === 'rechazada' ? 'rechazada' : 'pendiente';
}
