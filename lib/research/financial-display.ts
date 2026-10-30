// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS } from './metric-labels.ts';

/** Conserva la fecha de cierre: no convierte un ejercicio irregular en año natural. */
export function financialPeriod(value: string): string {
  if (value === 'unknown') return 'Periodo no informado por la fuente';
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
  ['where change_in_working_capital is in cash-flow sign (negative = working capital absorbed cash)', 'donde change_in_working_capital sigue el signo del flujo de caja (negativo = el capital circulante absorbió efectivo)'],
  ['change_in_working_capital in cash-flow sign', 'change_in_working_capital con el signo del flujo de caja'],
  ['(negative = working capital absorbed cash)', '(negativo = el capital circulante absorbió efectivo)'],
  ['maintenance_capex reported, or estimated as ', 'maintenance_capex publicada o, si no, estimada como '],
  [' when not separately reported (Buffett, Berkshire Hathaway 1986 letter)', ' cuando no se publica por separado (Buffett, carta de Berkshire Hathaway de 1986)'],
  ['maintenance capex is not separately reported - declared conservative estimate (Buffett owner earnings, Berkshire Hathaway 1986 letter)', 'la inversión de mantenimiento no se publica por separado: estimación conservadora declarada (beneficio del propietario de Buffett, carta de Berkshire Hathaway de 1986)'],
  ['maintenance capex is a declared conservative estimate (Buffett owner earnings, Berkshire Hathaway 1986 letter)', 'la inversión de mantenimiento es una estimación conservadora declarada (beneficio del propietario de Buffett, carta de Berkshire Hathaway de 1986)'],
  ['the maintenance/growth split is not separately reported - declared estimate', 'la separación mantenimiento/crecimiento no se publica por separado: estimación declarada'],
  ['and maintenance_capex', 'y maintenance_capex'],
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
  ['over up to 5 most recent fiscal years, minimum 3', 'de los últimos 5 ejercicios como máximo, con un mínimo de 3'],
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
  'Gross Margin': 'Margen bruto',
  'Operating Margin': 'Margen operativo',
  'Net Margin': 'Margen neto',
  'Total Assets': 'Activos totales',
  'Total Debt': 'Deuda total',
  'Total Equity': 'Patrimonio neto',
  'Cash And Equivalents': 'Efectivo y equivalentes',

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
  // Texto actual de financial_terminal_service.METRIC_DEFINITIONS_TEXT["owner_earnings"].
  'Buffett owner earnings (Berkshire Hathaway 1986 letter): net income + D&A + change in working capital (cash-flow sign: negative when working capital absorbs cash) - maintenance capex (estimated as min(|capex|, D&A) when not reported).':
    'Beneficio del propietario de Buffett (carta de Berkshire Hathaway de 1986): beneficio neto + depreciación y amortización + variación del capital circulante (con el signo del flujo de caja: negativa cuando el circulante absorbe caja) − inversión de mantenimiento (estimada como mínimo(|capex|, D&A) si no se publica).',
};

export function financialDefinition(value: string): string {
  return DEFINITIONS[value] ?? financialFormula(value);
}

/** Solo las versiones conocidas reciben un nombre; no inventa una versión. */
export function financialVersion(value: string): string {
  return ({ MARCO_V1: 'Marco de calidad · versión 1', MARCO_V2: 'Marco de calidad · versión 2' } as Record<string, string>)[value] ?? value;
}

/** El rango visible describe los datos cargados, no la ventana solicitada. */
export function loadedFinancialRange(metrics: Array<{ series: Array<{ period: string; value: string | number | null }> }>): string | null {
  const years = metrics.flatMap((metric) => metric.series.flatMap((point) => {
    if (point.value === null) return [];
    const match = /^(?:FY)?(\d{4})(?:$|[-:])/.exec(point.period);
    return match ? [Number(match[1])] : [];
  }));
  if (!years.length) return null;
  const first = Math.min(...years), last = Math.max(...years);
  return first === last ? String(first) : `${first}–${last}`;
}

/** Como financialVersion, pero sin mostrar claves internas: una versión no catalogada se muestra como "cálculo vN". */
export function financialVersionLabel(value: string): string {
  const known = financialVersion(value);
  if (known !== value) return known;
  const match = /_V(\d+)$/i.exec(value);
  return match ? `cálculo v${match[1]}` : 'cálculo sin versión';
}
