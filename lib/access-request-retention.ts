/**
 * TTL de Mongo sobre access_requests: APAGADO por defecto. Mongoose (autoIndex)
 * lo aplicaria a los documentos YA existentes y los borraria sin dry-run.
 * Devuelve los segundos del TTL solo si ACCESS_REQUEST_TTL_ENABLED=true; la
 * ventana sale de ACCESS_REQUEST_RETENTION_DAYS (invalido o <=0 cae a 365).
 */
export function accessRequestTtlSeconds(env: Record<string, string | undefined>): number | null {
  if (env.ACCESS_REQUEST_TTL_ENABLED !== 'true') return null;
  const days = Number(env.ACCESS_REQUEST_RETENTION_DAYS ?? 365);
  return (Number.isFinite(days) && days > 0 ? days : 365) * 86_400;
}
