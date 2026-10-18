// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS } from './metric-labels.ts';

/** Conserva la fecha de cierre: no convierte un ejercicio irregular en año natural. */
export function financialPeriod(value: string): string {
  if (value === 'unknown') return 'Periodo sin identificar';
  const dated = /^(\d{4})-(\d{2})-(\d{2}):(FY|Q[1-4])$/.exec(value);
  if (dated) return `${dated[4] === 'FY' ? 'Ejercicio' : `T${dated[4][1]}`} al ${dated[3]}/${dated[2]}/${dated[1]}`;
  return value.replace(/\bFY(?=\d)/g, 'Ejercicio ').replace(/\bQ([1-4])\b/g, 'T$1');
}

const WORDS: Record<string, string> = {
  ...METRIC_LABELS,
  average: 'media', mean: 'media', abs: 'valor absoluto', min: 'mínimo',
  equity_weight: 'peso del patrimonio', debt_weight: 'peso de la deuda',
  risk_free_rate: 'tipo libre de riesgo', equity_risk_premium: 'prima de riesgo de renta variable',
  country_risk_premium: 'prima de riesgo país', cost_of_debt: 'coste de la deuda', tax_rate: 'tipo impositivo',
  adjusted_invested_capital: 'capital invertido ajustado', maintenance_capex: 'inversión de mantenimiento',
};

const PHRASES: [string, string][] = [
  ['inflation-adjusted internal rate of return on gross investment; no proxy calculation is permitted', 'Tasa interna de rentabilidad de la inversión bruta ajustada por inflación; no admite cálculos sustitutivos'],
  ['using current invested capital when no coherent prior period exists', 'usa el capital invertido actual cuando no existe un periodo anterior comparable'],
  ['over up to 5 most recent fiscal years, minimum 3; coverage declared in trace', 'de los últimos 5 ejercicios como máximo, con un mínimo de 3; cobertura indicada en el desglose'],
  ['maintenance capex is not separately reported - declared conservative estimate (Buffet owner earnings)', 'la inversión de mantenimiento no se publica por separado: es una estimación conservadora (beneficio del propietario de Buffett)'],
  ['maintenance capex is a declared conservative estimate (Buffett owner earnings)', 'la inversión de mantenimiento es una estimación conservadora (beneficio del propietario de Buffett)'],
  ['approximate CFROI:', 'CFROI aproximado:'],
  ['DECLARED approximation - invested capital proxied by total_assets, no inflation adjustment, not comparable to Credit Suisse CFROI', 'aproximación: usa los activos totales como sustituto del capital invertido, sin ajuste de inflación; no es comparable al CFROI de Credit Suisse'],
  ['count of passed checks:', 'número de criterios superados:'],
  ['each check traceable with its value and threshold', 'cada criterio incluye su valor y umbral en el desglose'],
  ['1.0 = maintenance-only investment, higher = growth or capital intensity', '1,0 = inversión solo de mantenimiento; un valor mayor indica crecimiento o intensidad de capital'],
  ['V1 checks', 'criterios de la versión 1'],
  ['mean of annual', 'media anual de'], ['where', 'donde'], ['plus', 'más'],
];

/** Traduce términos, no altera operaciones, umbrales ni versiones de cálculo. */
export function financialFormula(value: string): string {
  let text = value;
  for (const [from, to] of PHRASES) text = text.replaceAll(from, to);
  return text.replace(/\b[A-Za-z][A-Za-z0-9_]*\b/g, (word) => WORDS[word] ?? word);
}

export function financialSegment(value: string): string {
  return value === 'consolidated' ? 'Consolidado' : value;
}

const DEFINITIONS: Record<string, string> = {
  'Reported consolidated or segment revenue.': 'Ingresos publicados, consolidados o por segmento.',
  'Diluted earnings per share reported for the period.': 'Beneficio diluido por acción publicado para el periodo.',
  'Operating cash flow less capital expenditure.': 'Flujo de caja operativo menos inversión de capital.',
  'Free cash flow divided by diluted shares.': 'Flujo de caja libre dividido entre acciones diluidas.',
  'After-tax operating profit divided by invested capital.': 'Beneficio operativo después de impuestos dividido entre capital invertido.',
  'Operating profit divided by capital employed.': 'Beneficio operativo dividido entre capital empleado.',
  'Change in operating profit after tax divided by change in invested capital.': 'Variación del beneficio operativo después de impuestos dividida entre la variación del capital invertido.',
  'Weighted-average diluted shares for the period.': 'Media ponderada de acciones diluidas del periodo.',
  'Stock-based compensation expense.': 'Gasto de remuneración en acciones.',
  'Operating current assets less operating current liabilities.': 'Activos corrientes operativos menos pasivos corrientes operativos.',
  'Cash investment in property, plant and equipment.': 'Inversión en efectivo en inmovilizado material.',
  'Net income plus D&A less maintenance capex and normalized working-capital needs.': 'Beneficio neto más depreciación y amortización, menos inversión de mantenimiento y necesidades normalizadas de capital circulante.',
};

export function financialDefinition(value: string): string {
  return DEFINITIONS[value] ?? financialFormula(value);
}
