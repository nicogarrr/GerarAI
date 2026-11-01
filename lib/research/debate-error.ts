// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';

/** Only allow fixed public backend reasons, never raw provider bodies or URLs. */
const PUBLIC_DEBATE_ERRORS = new Map([
  ['LLM gratuito agotado, vuelve más tarde', 'research.debateErrors.freeExhausted'],
  ['LLM gratuito no disponible, vuelve más tarde', 'research.debateErrors.freeUnavailable'],
  ['Presupuesto LLM agotado, vuelve más tarde', 'research.debateErrors.budgetExhausted'],
  ['El debate tardó demasiado; vuelve más tarde', 'research.debateErrors.timeout'],
  ['El debate devolvió una respuesta no válida; vuelve más tarde', 'research.debateErrors.invalidAnswer'],
] as const);

/** Motivo público del fallo del debate en el idioma elegido (español por defecto; el backend lo manda en español). */
export function debateErrorMessage(error: unknown, locale: 'es' | 'en' = 'es'): string {
  const t = createTranslator(locale);
  if (!(error instanceof Error)) return t('research.debateErrors.generic');
  const known = PUBLIC_DEBATE_ERRORS.get(error.message as never);
  if (known) return t(known);
  // researchRequest wraps fetch exceptions in ExternalAPIError.originalError.
  const original = (error as Error & { originalError?: unknown }).originalError;
  const name = original instanceof Error ? original.name : error.name;
  if (name === 'TimeoutError' || name === 'AbortError') {
    return t('research.debateErrors.timeout');
  }
  return t('research.debateErrors.generic');
}
