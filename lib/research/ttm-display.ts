/**
 * Presentación de los fundamentales actuales en TTM (últimos 4 trimestres).
 * Funciones puras: la fórmula vive en el backend (GET /api/companies/{ticker}/ttm),
 * aquí solo se etiqueta, sin inventar nada. Un valor ausente es «N/D» y su
 * base «Sin datos».
 */

export type TtmBasis = 'TTM' | 'FY' | 'Q' | 'SIN_DATOS';
export type TtmProvenance = 'OFICIAL' | 'INFERIDO' | 'SIN_DATOS';

export type ResearchTtmQuarter = {
  period_end: string;
  value: string | number;
  reported: boolean;
  origin: string;
};

export type ResearchTtmMetric = {
  metric: string;
  value: string | number | null;
  unit: string | null;
  basis: TtmBasis;
  label: string;
  provenance: TtmProvenance;
  period_end: string | null;
  note?: string | null;
  fact_ids?: number[];
  quarters?: ResearchTtmQuarter[];
};

export type ResearchTtm = {
  ticker: string;
  as_of: string | null;
  formula: string;
  metrics: ResearchTtmMetric[];
};

const BASIS_LABEL: Record<TtmBasis, string> = {
  TTM: 'TTM (últimos 4 trimestres)',
  FY: 'FY (último ejercicio)',
  Q: 'Último trimestre',
  SIN_DATOS: 'Sin datos',
};

/** «2026-06-27» → «27/06/2026» (sin pasar por Date: nada de husos). */
export function isoDateEs(value: string | null | undefined): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  return match ? `${match[3]}/${match[2]}/${match[1]}` : null;
}

export function ttmBasisLabel(basis: TtmBasis): string {
  return BASIS_LABEL[basis] ?? BASIS_LABEL.SIN_DATOS;
}

/** Línea de periodo bajo la cifra: «TTM (últimos 4 trimestres) · hasta 27/06/2026». */
export function ttmPeriodText(metric: Pick<ResearchTtmMetric, 'basis' | 'period_end'>): string {
  const label = ttmBasisLabel(metric.basis);
  const end = isoDateEs(metric.period_end);
  if (metric.basis === 'SIN_DATOS' || !end) return label;
  return metric.basis === 'TTM' ? `${label} · hasta ${end}` : `${label} · cierre ${end}`;
}

/** Desglose de los trimestres sumados, marcando los inferidos. */
export function ttmQuartersText(quarters: ResearchTtmQuarter[] | undefined): string | null {
  if (!quarters || quarters.length === 0) return null;
  return quarters
    .map((q) => {
      const end = isoDateEs(q.period_end) ?? q.period_end;
      if (q.origin === 'FY-9M') return `${end} (Q4 = FY − 9 meses, inferido)`;
      if (!q.reported) return `${end} (acumulado restado, inferido)`;
      return end;
    })
    .join(' + ');
}

/** Métricas que se enseñan en la ficha, en este orden (las demás siguen en la API). */
export const TTM_PANEL_METRICS = [
  'revenue',
  'operating_income',
  'net_income',
  'eps_diluted',
  'operating_cash_flow',
  'free_cash_flow',
  'cash_and_equivalents',
  'total_debt',
  'net_debt',
  'total_equity',
] as const;

export function ttmPanelMetrics(ttm: ResearchTtm | null): ResearchTtmMetric[] {
  if (!ttm) return [];
  const byMetric = new Map(ttm.metrics.map((m) => [m.metric, m]));
  return TTM_PANEL_METRICS.map((key) => byMetric.get(key)).filter(
    (m): m is ResearchTtmMetric => m !== undefined,
  );
}

/** Hay algo que enseñar solo si al menos una métrica tiene valor. */
export function ttmHasData(ttm: ResearchTtm | null): boolean {
  return ttmPanelMetrics(ttm).some((m) => m.value !== null && m.basis !== 'SIN_DATOS');
}
