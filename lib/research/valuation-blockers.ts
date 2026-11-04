/**
 * Causas máquina del «sin DCF» del modelo a largo plazo
 * (long_term_model_service._scenario_payload → valuation_blockers).
 * Catálogo cerrado: un token desconocido devuelve null y la UI cae a
 * valuation_note en crudo; nunca se oculta la causa de un N/D.
 */
import type { TranslationKey } from '@/lib/i18n/t';

export const VALUATION_BLOCKER_KEYS: Record<string, TranslationKey> = {
  forecast_missing: 'research.model.valuationBlocker.forecastMissing',
  current_net_debt_missing: 'research.model.valuationBlocker.currentNetDebtMissing',
  terminal_shares_missing: 'research.model.valuationBlocker.terminalSharesMissing',
  wacc_not_above_terminal_growth: 'research.model.valuationBlocker.waccNotAboveTerminalGrowth',
  terminal_fcf_not_positive: 'research.model.valuationBlocker.terminalFcfNotPositive',
};

export function valuationBlockerKey(token: string): TranslationKey | null {
  return VALUATION_BLOCKER_KEYS[token] ?? null;
}

type ScenarioLike = {
  valuation?: unknown;
  valuation_blockers?: string[] | null;
  valuation_note?: string | null;
};

/**
 * Causa legible del N/D de valor/acción de un escenario, o null si hay
 * valoración o no se conoce la causa. Tokens traducidos y unidos; si algún
 * token es desconocido, la nota original del backend (nunca se oculta).
 */
export function scenarioValuationCause(
  scenario: ScenarioLike,
  ti: (key: TranslationKey) => string,
): string | null {
  if (scenario.valuation != null) return null;
  const blockers = scenario.valuation_blockers ?? [];
  if (blockers.length) {
    const labels = blockers.map((token) => {
      const key = valuationBlockerKey(token);
      return key ? ti(key) : null;
    });
    if (labels.every((label) => label != null)) return (labels as string[]).join(' · ');
  }
  return scenario.valuation_note ?? null;
}

/**
 * Causas unidas de todos los escenarios sin valoración, en orden y sin
 * repetir; vacío si algún escenario sí tiene valoración o no hay causas
 * conocidas. Para la cabecera del panel («valor/acción no calculable: …»).
 */
export function modelUnvaluedCauseKeys(
  scenarios: Record<string, ScenarioLike>,
): TranslationKey[] {
  const list = Object.values(scenarios);
  if (!list.length || list.some((s) => s.valuation != null)) return [];
  const keys: TranslationKey[] = [];
  for (const scenario of list) {
    for (const token of scenario.valuation_blockers ?? []) {
      const key = valuationBlockerKey(token);
      if (key && !keys.includes(key)) keys.push(key);
    }
  }
  return keys;
}
