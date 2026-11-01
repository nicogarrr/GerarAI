/**
 * Presentación de los fundamentales actuales en TTM (últimos 4 trimestres).
 * Funciones puras: la fórmula vive en el backend (GET /api/companies/{ticker}/ttm),
 * aquí solo se etiqueta, sin inventar nada. Un valor ausente es «N/D» y su
 * base «Sin datos».
 */

// @ts-expect-error TS5097
import { DEFAULT_LOCALE, type Locale } from '../i18n/locale.ts';
import type { TranslationKey } from '../i18n/t.ts';
// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';

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

const BASIS_KEY: Record<TtmBasis, TranslationKey> = {
  TTM: 'research.ttm.basisTtm',
  FY: 'research.ttm.basisFy',
  Q: 'research.ttm.basisQ',
  SIN_DATOS: 'research.ttm.noData',
};

export function isoDateEs(value: string | null | undefined): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  return match ? `${match[3]}/${match[2]}/${match[1]}` : null;
}

/** Fecha corta del periodo: dd/mm/aaaa en español, aaaa-mm-dd (sin ambigüedad) en inglés. */
function periodDate(value: string | null | undefined, locale: Locale): string | null {
  if (locale === 'es') return isoDateEs(value);
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value ?? '');
  return match ? match[1] : null;
}

export function ttmBasisLabel(basis: TtmBasis, locale: Locale = DEFAULT_LOCALE): string {
  return createTranslator(locale)(BASIS_KEY[basis] ?? BASIS_KEY.SIN_DATOS);
}

/** Etiqueta de procedencia (OFICIAL / INFERIDO / Sin datos) en el idioma elegido. */
export function ttmProvenanceLabel(provenance: TtmProvenance | string, locale: Locale = DEFAULT_LOCALE): string {
  const t = createTranslator(locale);
  if (provenance === 'SIN_DATOS') return t('research.ttm.noData');
  if (provenance === 'OFICIAL') return t('research.ttm.provOfficial');
  if (provenance === 'INFERIDO') return t('research.ttm.provInferred');
  return provenance;
}

/** Línea de periodo bajo la cifra: «TTM (últimos 4 trimestres) · hasta 27/06/2026». */
export function ttmPeriodText(metric: Pick<ResearchTtmMetric, 'basis' | 'period_end'>, locale: Locale = DEFAULT_LOCALE): string {
  const t = createTranslator(locale);
  const label = ttmBasisLabel(metric.basis, locale);
  const end = periodDate(metric.period_end, locale);
  if (metric.basis === 'SIN_DATOS' || !end) return label;
  return metric.basis === 'TTM' ? t('research.ttm.periodUntil', { label, date: end }) : t('research.ttm.periodClose', { label, date: end });
}

/** Desglose de los trimestres sumados, marcando los inferidos. */
export function ttmQuartersText(quarters: ResearchTtmQuarter[] | undefined, locale: Locale = DEFAULT_LOCALE): string | null {
  if (!quarters || quarters.length === 0) return null;
  const t = createTranslator(locale);
  return quarters
    .map((q) => {
      const end = periodDate(q.period_end, locale) ?? q.period_end;
      if (q.origin === 'FY-9M') return t('research.ttm.quarterQ4Inferred', { date: end });
      if (!q.reported) return t('research.ttm.quarterCumulativeInferred', { date: end });
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
