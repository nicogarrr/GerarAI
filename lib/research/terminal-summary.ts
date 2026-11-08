/**
 * Resumen determinista de la serie anual de una métrica del Terminal (sin
 * modelo): años cubiertos, media, mínimo y máximo y, para importes y acciones,
 * la tasa de crecimiento anual compuesta (TACC/CAGR) entre el primer y el
 * último ejercicio. Solo ejercicios completos (FY) consolidados con valor;
 * un año = una cifra (reportada > normalizada > calculada).
 */
export interface TerminalPoint {
  period: string;
  value: string | number | null;
  unit: string;
  status: string;
  segment: string | null;
}

export interface AnnualSummary {
  years: number;
  firstYear: number;
  lastYear: number;
  unit: string;
  mean: number;
  min: { year: number; value: number };
  max: { year: number; value: number };
  /** null si no aplica (ratios/porcentajes, signo cambiante o un solo año). */
  cagr: number | null;
  /** Por qué no hay TACC, cuando no la hay. */
  cagrReason: 'ratio' | 'sign' | 'single_year' | null;
}

const RATIO_OR_PERCENT = new Set(['decimal', 'ratio', 'fraction', 'fraccion', '%', 'pct', 'percent', 'percentage', 'porcentaje', 'x', 'times', 'pure']);
const STATUS_RANK: Record<string, number> = { reported: 0, normalized: 1, calculated: 2 };

/** Año fiscal de un periodo anual («2024-12-31:FY», «FY2024», «2024»); null si no es anual. */
export function fiscalYear(period: string): number | null {
  const dated = /^(\d{4})-\d{2}-\d{2}:FY$/.exec(period);
  if (dated) return Number(dated[1]);
  const fy = /^FY\s?(\d{4})$/i.exec(period) ?? /^(\d{4})$/.exec(period);
  return fy ? Number(fy[1]) : null;
}

function isConsolidated(segment: string | null): boolean {
  return !segment || segment === 'consolidated' || segment === 'total';
}

export function annualSummary(series: TerminalPoint[]): AnnualSummary | null {
  const byYear = new Map<number, { value: number; unit: string; rank: number }>();
  for (const point of series) {
    const year = fiscalYear(point.period);
    const value = point.value === null ? NaN : Number(point.value);
    if (year === null || !Number.isFinite(value) || !isConsolidated(point.segment)) continue;
    const rank = STATUS_RANK[point.status] ?? 3;
    const current = byYear.get(year);
    if (!current || rank < current.rank) byYear.set(year, { value, unit: (point.unit ?? '').trim(), rank });
  }
  if (byYear.size === 0) return null;
  // Una sola unidad: la del ejercicio más reciente (nunca se mezclan USD y EUR).
  const years = [...byYear.keys()].sort((a, b) => a - b);
  const unit = byYear.get(years[years.length - 1])!.unit;
  const rows = years.map((year) => ({ year, ...byYear.get(year)! })).filter((row) => row.unit === unit);
  const first = rows[0];
  const last = rows[rows.length - 1];
  let min = first;
  let max = first;
  for (const row of rows) {
    if (row.value < min.value) min = row;
    if (row.value > max.value) max = row;
  }
  const mean = rows.reduce((sum, row) => sum + row.value, 0) / rows.length;
  const span = last.year - first.year;
  let cagr: number | null = null;
  let cagrReason: AnnualSummary['cagrReason'] = null;
  if (RATIO_OR_PERCENT.has(unit.toLowerCase())) cagrReason = 'ratio';
  else if (span < 1) cagrReason = 'single_year';
  else if (first.value <= 0 || last.value <= 0) cagrReason = 'sign';
  else cagr = ((last.value / first.value) ** (1 / span) - 1) * 100;
  return {
    years: rows.length, firstYear: first.year, lastYear: last.year, unit, mean,
    min: { year: min.year, value: min.value }, max: { year: max.year, value: max.value }, cagr, cagrReason,
  };
}
