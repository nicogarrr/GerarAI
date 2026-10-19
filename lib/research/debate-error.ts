/** Only allow fixed public backend reasons, never raw provider bodies or URLs. */
const PUBLIC_DEBATE_ERRORS = new Set([
  'LLM gratuito agotado, vuelve más tarde',
  'LLM gratuito no disponible, vuelve más tarde',
  'Presupuesto LLM agotado, vuelve más tarde',
  'El debate tardó demasiado; vuelve más tarde',
  'El debate devolvió una respuesta no válida; vuelve más tarde',
]);

export function debateErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) return 'No se pudo generar el debate; reinténtalo.';
  if (PUBLIC_DEBATE_ERRORS.has(error.message)) return error.message;
  // researchRequest wraps fetch exceptions in ExternalAPIError.originalError.
  const original = (error as Error & { originalError?: unknown }).originalError;
  const name = original instanceof Error ? original.name : error.name;
  if (name === 'TimeoutError' || name === 'AbortError') {
    return 'El debate tardó demasiado; vuelve más tarde';
  }
  return 'No se pudo generar el debate; reinténtalo.';
}
