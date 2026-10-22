/**
 * Puerta de fase del seguimiento de compromisos (migraciones 0078/0079/0080).
 * Variable SOLO de servidor, sin NEXT_PUBLIC y sin secretos. Ocultar la UI no
 * sustituye la autorizacion del backend: es solo para que un frontend nuevo
 * no llame a rutas que un backend viejo aun no tiene.
 * Activa solo con COMMITMENTS_UI_ENABLED=1 (por defecto apagada).
 */
export function commitmentsUiEnabled(): boolean {
  return process.env.COMMITMENTS_UI_ENABLED === '1';
}
