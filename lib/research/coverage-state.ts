// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

export const NOT_VALUABLE = 'No valorable / falta evidencia';

/** Coverage counts stored layers. It never establishes valuation quality. */
export function researchValuability(snapshot: {
  latest_thesis?: { status: string } | null;
  model_summary?: { status: string; publishable: boolean } | null;
  valuation_summary: { status: string };
}): string {
  const thesis = snapshot.latest_thesis;
  const model = snapshot.model_summary;
  // 'missing_mandatory_drivers' ya no bloquea (27/10/2026): un KPI operativo sin
  // dato se declara «sin dato (motivo)» y no impide valorar con los inputs centrales.
  const blocked = new Set(['insufficient_data', 'blocked', 'preview_only']);
  if (!thesis || !model || blocked.has(thesis.status) || blocked.has(model.status) ||
      blocked.has(snapshot.valuation_summary.status) || !model.publishable) {
    return NOT_VALUABLE;
  }
  return 'Revisar tesis y supuestos';
}

/** A forecast condition is not evidence that the condition was met. */
export function modelConditionState(item: {
  id: string; value: number | null; comparison?: number | null; status: string;
}, hasWaccSource: boolean, ti: TiFn = esT): string {
  if (item.status === 'out_of_bounds') return ti('research.condState.outOfRange');
  if (item.id === 'roic_above_wacc' && (!hasWaccSource || item.comparison == null || !Number.isFinite(item.comparison))) {
    return ti('research.condState.waccMissing');
  }
  if (item.id === 'fcf_margin' && item.value != null && item.value < -1) {
    return ti('research.condState.fcfOutOfRange');
  }
  if (item.value == null || !Number.isFinite(item.value) || item.status.startsWith('blocked')) {
    return ti('research.condState.noEvidence');
  }
  return ti('research.condState.toVerify');
}

/** Ratings del motor de tesis que son un veredicto de valoración. */
const VALUATION_VERDICTS = new Set(['attractive', 'expensive', 'fair', 'cheap', 'incomplete_price']);

/** Un veredicto de valoración (atractiva/cara) no puede convivir con un estado
 *  «no valorable»: si la valoración no es válida, el veredicto se omite
 *  (null). Los demás ratings (compra, mantener, datos insuficientes...) pasan. */
export function visibleThesisRating(
  rating: string | null | undefined,
  snapshot: Parameters<typeof researchValuability>[0],
): string | null {
  if (!rating) return null;
  if (VALUATION_VERDICTS.has(rating) && researchValuability(snapshot) === NOT_VALUABLE) return null;
  return rating;
}
