// @ts-expect-error TS5097: extensión explícita requerida por los guards node strip-types.
import { formatNumberForInput, parseLocalizedNumberDetailed } from './format.ts';

/** Unidad en la que el backend guarda la métrica y cómo la escribe una persona. */
export type MetricUnit = { suffix: string; factor: number; step: string };

export const UNITS = {
  ratio: { suffix: '%', factor: 0.01, step: '0.1' },
  usd: { suffix: 'M $', factor: 1_000_000, step: '100' },
  multiple: { suffix: '×', factor: 1, step: '0.1' },
  number: { suffix: '', factor: 1, step: 'any' },
} as const satisfies Record<string, MetricUnit>;

export type UnitKind = keyof typeof UNITS;

const GROUPS: { title: string; en: string; unit: UnitKind; keys: string[] }[] = [
  { title: 'Rentabilidad', en: 'Profitability', unit: 'ratio', keys: ['roic', 'roic_adjusted', 'roe', 'roa', 'roce', 'cfroi', 'cfroi_approx', 'roe_5y', 'roa_5y', 'wacc'] },
  { title: 'Márgenes', en: 'Margins', unit: 'ratio', keys: ['gross_margin', 'operating_margin', 'net_margin', 'fcf_margin', 'net_margin_5y', 'fcf_margin_5y', 'effective_tax_rate', 'fcf_conversion'] },
  { title: 'Crecimiento', en: 'Growth', unit: 'ratio', keys: ['revenue_growth', 'shares_cagr', 'capex_to_revenue'] },
  { title: 'Deuda', en: 'Debt', unit: 'multiple', keys: ['net_debt_to_ebitda', 'debt_to_equity'] },
  { title: 'Tamaño y valoración', en: 'Size and valuation', unit: 'usd', keys: ['market_cap'] },
  { title: 'Resultados', en: 'Earnings', unit: 'usd', keys: ['revenue', 'gross_profit', 'operating_income', 'net_income', 'ebitda'] },
  { title: 'Flujo de caja', en: 'Cash flow', unit: 'usd', keys: ['operating_cash_flow', 'free_cash_flow', 'capital_expenditure', 'dividends_paid'] },
  { title: 'Balance', en: 'Balance sheet', unit: 'usd', keys: ['total_assets', 'total_liabilities', 'total_equity', 'total_debt', 'net_debt', 'cash_and_equivalents', 'goodwill'] },
  { title: 'Calidad', en: 'Quality', unit: 'number', keys: ['quality_moat_score', 'quality_moat_score_v2'] },
  // Conexiones con el resto de la app (data-engine/app/services/screener_context_metrics.py):
  // margen del motor de valoración, si hay tesis y el nivel del motor DCA.
  { title: 'Valoración', en: 'Valuation', unit: 'ratio', keys: ['margen_seguridad'] },
  { title: 'Tesis y nivel DCA', en: 'Thesis and DCA level', unit: 'number', keys: ['tiene_tesis', 'tesis_publicada', 'nivel_dca'] },
];

// Títulos de grupo en inglés: el grupo se guarda con su título español (es su
// identificador en tests y datos) y solo se traduce al mostrarse.
const CUSTOM_GROUP = 'Personalizadas';
const OTHER_GROUP = 'Otras';
const GROUP_LABELS_EN = new Map<string, string>([
  ...GROUPS.map((g) => [g.title, g.en] as [string, string]),
  [CUSTOM_GROUP, 'Custom'],
  [OTHER_GROUP, 'Other'],
]);

/** Título visible de un grupo de métricas en el idioma elegido. */
export function metricGroupLabel(group: string, locale: 'es' | 'en' = 'es'): string {
  return locale === 'en' ? (GROUP_LABELS_EN.get(group) ?? group) : group;
}

const BY_KEY = new Map<string, { group: string; unit: UnitKind }>();
for (const g of GROUPS) for (const k of g.keys) BY_KEY.set(k, { group: g.title, unit: g.unit });

export type MetricOption = { key: string; label: string; group: string; unit: UnitKind; hasData: boolean };


/**
 * Métricas elegibles. Las personalizadas usan el valor tal cual lo devuelve su
 * fórmula: el backend guarda la unidad solo como etiqueta, sin escala fija.
 * Con cobertura conocida solo salen las que tienen datos de
 * alguna empresa; sin cobertura (motor caído) se ofrece el catálogo completo.
 */
export function buildMetricOptions(
  available: readonly string[] | undefined,
  custom: readonly { metric_key: string; name: string; unit: string }[] = [],
  metricLabel: (key: string) => string = (key) => key.replaceAll('_', ' '),
): MetricOption[] {
  const have = available === undefined ? null : new Set(available);
  const out: MetricOption[] = [];
  const seen = new Set<string>();
  for (const g of GROUPS) {
    for (const key of g.keys) {
      if (have && !have.has(key)) continue;
      seen.add(key);
      out.push({ key, label: metricLabel(key), group: g.title, unit: g.unit, hasData: true });
    }
  }
  for (const c of custom) {
    if (seen.has(c.metric_key)) continue;
    seen.add(c.metric_key);
    out.push({ key: c.metric_key, label: c.name, group: CUSTOM_GROUP, unit: 'number', hasData: true });
  }
  if (have) {
    for (const key of have) {
      if (seen.has(key) || /[*\s]/.test(key)) continue;
      out.push({ key, label: metricLabel(key), group: OTHER_GROUP, unit: BY_KEY.get(key)?.unit ?? 'number', hasData: true });
    }
  }
  return out;
}

/** Valor que se manda al backend a partir de lo que ve la persona (15 % -> 0.15). */
export function toBackendValue(shown: string, unit: UnitKind, locale: 'es' | 'en' = 'es'): string {
  // Gramática es-ES compartida (lib/format): «12,5» y «1.234,56» valen;
  // los ambiguos («1,234») se rechazan en lugar de reinterpretarse x1000.
  const parsed = parseLocalizedNumberDetailed(shown, locale);
  if (!parsed.ok) return '';
  return String(Number((parsed.value * UNITS[unit].factor).toPrecision(12)));
}

/** ¿El texto del valor es rechazado por la gramática es-ES? (para el aviso en el campo) */
export function shownValueError(shown: string, locale: 'es' | 'en' = 'es'): 'ambiguous' | 'invalid' | null {
  if (!shown.trim()) return null;
  const parsed = parseLocalizedNumberDetailed(shown, locale);
  if (parsed.ok) return null;
  return parsed.error === 'ambiguous' ? 'ambiguous' : 'invalid';
}

/** Inverso: valor del backend al que se muestra (0.15 -> 15). */
export function fromBackendValue(raw: string, unit: UnitKind, locale: 'es' | 'en' = 'es'): string {
  const n = Number(raw);
  if (!raw.trim() || !Number.isFinite(n)) return '';
  // Se escribe como lo relee toBackendValue (gramática es-ES): con String() salía
  // «1.234» con punto, que es-ES lee como MILES, y editar un screen guardado
  // convertía el valor 1,234 en 1234 sin tocar nada.
  return formatNumberForInput(Number((n / UNITS[unit].factor).toPrecision(12)), locale);
}
