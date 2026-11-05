/**
 * Presentación de la valoración del motor (vista «Valoración» de la ficha).
 * Funciones puras y defensivas: la traza del motor es un dict libre; un
 * campo ausente degrada a null (la vista omite la línea), nunca se inventa.
 */
import { formatPercent } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';

/** Motivos de no publicación: claves i18n (research.valuationText.blockers.*).
 *  «traceable_wacc» como blocker significa que FALTA (el token suelto se leía
 *  como «WACC con fuente trazable», justo lo contrario). */
const BLOCKER_LABEL_KEYS: Record<string, TranslationKey> = {
  traceable_wacc: 'research.valuationText.blockers.traceableWacc',
  forecast_is_not_the_driver: 'research.valuationText.blockers.forecastIsNotTheDriver',
  inferred_fcf_margin_target: 'research.valuationText.blockers.inferredFcfMarginTarget',
  scenario_set_missing: 'research.valuationText.blockers.scenarioSetMissing',
};

export function blockerLabel(id: string, locale: 'es' | 'en' = 'es'): string {
  const key = BLOCKER_LABEL_KEYS[id];
  return key ? createTranslator(locale)(key) : id;

}

/** Procedencia del WACC usado por el motor (resolve_rates del backend). */
export function waccSourceLabel(source: string | null | undefined, locale: Locale = 'es'): string | null {
  if (!source) return null;
  const t = createTranslator(locale);
  switch (source) {
    case 'calculated_metric': return t('research.valuationText.waccSource.calculated_metric');
    case 'inferred_input': return t('research.valuationText.waccSource.inferred_input');
    case 'declared_input': return t('research.valuationText.waccSource.declared_input');
    case 'tag_default': return t('research.valuationText.waccSource.tag_default');
    case 'market_cap_band': return t('research.valuationText.waccSource.market_cap_band');
    default: return source;
  }
}

type ReverseDcfLike = {
  status?: string;
  required_revenue_growth?: number | null;
  out_of_bounds?: boolean;
  fcf_margin?: number | null;
  wacc?: number | null;
};

// Dos decimales: un margen FCF del 1,07 % no se puede redondear a «1,1 %»
// (el contexto de la cifra es justamente ese segundo decimal).
const pct = (value: number | null | undefined, locale: Locale = 'es') =>
  value == null || !Number.isFinite(value) ? null : formatPercent(value, { digits: 2 }, undefined, locale);

/** DCF inverso en una frase; null cuando el motor no devolvió nada que contar. */
export function reverseDcfText(reverse: ReverseDcfLike | null | undefined, locale: Locale = 'es'): string | null {
  if (!reverse || typeof reverse !== 'object') return null;
  const t = createTranslator(locale);
  const status = reverse.status ?? (reverse.required_revenue_growth != null ? 'ok' : null);
  if (status === 'ok') {
    const growth = pct(reverse.required_revenue_growth, locale);
    if (!growth) return null;
    const margin = pct(reverse.fcf_margin, locale);
    const wacc = pct(reverse.wacc, locale);
    const basis = margin && wacc ? t('research.valuationText.reverseBasis', { margin, wacc }) : '';
    return t('research.valuationText.reverseOk', { growth, basis });
  }
  if (status === 'out_of_bounds') return t('research.valuationText.reverseOutOfBounds');
  if (status === 'not_applicable') return t('research.valuationText.reverseNotApplicable');
  return null;
}

type TraceLike = {
  scenarios?: unknown;
  periods?: Record<string, string | null> | undefined;
  wacc?: unknown;
  wacc_source?: unknown;
};

function baseAssumptions(trace: TraceLike): { fcf_margin?: unknown; revenue_growth?: unknown } {
  const scenarios = trace.scenarios as Record<string, { definition?: { assumptions?: Record<string, unknown> } }> | undefined;
  return scenarios?.base?.definition?.assumptions ?? {};
}

/** «Supuestos del escenario base: margen FCF 1,07 % (periodo FY2025) ·
 *  crecimiento de ingresos 7 % · WACC 9 % (…)». null si no hay nada que decir. */
export function baseAssumptionsText(trace: TraceLike | null | undefined, locale: Locale = 'es'): string | null {
  if (!trace || typeof trace !== 'object') return null;
  const t = createTranslator(locale);
  const assumptions = baseAssumptions(trace);
  const parts: string[] = [];
  const margin = typeof assumptions.fcf_margin === 'number' ? pct(assumptions.fcf_margin, locale) : null;
  if (margin) {
    const period = trace.periods?.fcf_margin ?? trace.periods?.free_cash_flow ?? null;
    parts.push(period
      ? t('research.valuationText.marginPeriod', { value: margin, period })
      : t('research.valuationText.margin', { value: margin }));
  }
  const growth = typeof assumptions.revenue_growth === 'number' ? pct(assumptions.revenue_growth, locale) : null;
  if (growth) parts.push(t('research.valuationText.growth', { value: growth }));
  const waccValue = typeof trace.wacc === 'number' ? pct(trace.wacc, locale) : null;
  if (waccValue) {
    const source = waccSourceLabel(typeof trace.wacc_source === 'string' ? trace.wacc_source : null, locale);
    parts.push(source
      ? t('research.valuationText.waccWithSource', { value: waccValue, source })
      : t('research.valuationText.wacc', { value: waccValue }));
  }
  if (parts.length === 0) return null;
  return t('research.valuationText.assumptions', { parts: parts.join(' · ') });
}

type ScenarioWarning = {
  id?: string;
  value?: number;
  reference?: number;
  reference_low?: number;
  reference_high?: number;
};

/** Avisos de supuestos de escenarios declarados fuera de la referencia general
 *  (decisión 4-nov-2026: con fuente no se rechaza ni se oculta; se avisa). */
export function scenarioWarningLines(trace: unknown, locale: Locale = 'es'): string[] {
  const set = (trace as { scenario_set?: { scenarios?: unknown } } | null | undefined)?.scenario_set;
  const scenarios = set?.scenarios;
  if (!Array.isArray(scenarios)) return [];
  const t = createTranslator(locale);
  const lines: string[] = [];
  for (const scenario of scenarios as { name?: unknown; warnings?: ScenarioWarning[] }[]) {
    const name = typeof scenario.name === 'string' ? scenario.name : '?';
    for (const warning of scenario.warnings ?? []) {
      const value = pct(warning.value, locale);
      if (warning.id === 'growth_outside_reference' && value) {
        lines.push(t('research.valuationText.scenarioWarnings.growthOutsideReference', {
          name, value,
          low: pct(warning.reference_low, locale) ?? 'N/D',
          high: pct(warning.reference_high, locale) ?? 'N/D',
        }));
      } else if (warning.id === 'margin_above_reference' && value) {
        lines.push(t('research.valuationText.scenarioWarnings.marginAboveReference', {
          name, value,
          reference: pct(warning.reference, locale) ?? 'N/D',
        }));
      }
    }
  }
  return lines;
}

/** Notas N/D de escenarios (bear/base/bull/expected) en orden estable. */
export function scenarioNotesList(notes: Record<string, string> | null | undefined): string[] {
  if (!notes || typeof notes !== 'object') return [];
  const order = ['bear', 'base', 'bull', 'expected'];
  return order.filter((key) => typeof notes[key] === 'string' && notes[key]).map((key) => notes[key]);
}
