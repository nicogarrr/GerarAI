import Link from 'next/link';
import { ChevronRight } from 'lucide-react';

import type { AnalystTargets } from '@/lib/research/analyst-targets';
import type { KeyStats } from '@/lib/research/key-stats';
import type { ResearchLongTermModel, MoatScoreMetric } from '@/lib/actions/research.actions';
import type { ShareCapital } from '@/lib/actions/share-capital.actions';
import type { ManagementCredibility } from '@/components/research/sections/ManagementCredibilitySection';
import { formatMarketDate, formatNumber, formatPrice, formatPercent } from '@/lib/format';
import { getT } from '@/lib/i18n/server';

const GRADE_KEYS = {
  high: 'research.credibility.grade.high',
  mixed: 'research.credibility.grade.mixed',
  low: 'research.credibility.grade.low',
  insufficient_history: 'research.credibility.grade.insufficientHistory',
} as const;

function Row({ href, label, value, note }: { href?: string; label: string; value: string; note?: string }) {
  if (!href) {
    // Dato de mercado sin sección propia en la ficha: fila informativa, sin enlace.
    return (
      <li className="flex min-h-[44px] items-center justify-between gap-3 border-b border-gray-800/70 py-2 last:border-0">
        <span className="min-w-0">
          <span className="block text-xs text-gray-500">{label}</span>
          {note ? <span className="mt-0.5 block text-[11px] leading-4 text-gray-500">{note}</span> : null}
        </span>
        <span className="shrink-0 text-sm font-semibold text-gray-100">{value}</span>
      </li>
    );
  }
  return (
    <li>
      <Link className="group flex min-h-[44px] items-center justify-between gap-3 border-b border-gray-800/70 py-2 last:border-0" href={href} scroll={false}>
        <span className="min-w-0">
          <span className="block text-xs text-gray-500">{label}</span>
          {note ? <span className="mt-0.5 block text-[11px] leading-4 text-gray-500">{note}</span> : null}
        </span>
        <span className="flex shrink-0 items-center gap-1 text-sm font-semibold text-gray-100 group-hover:text-teal-200">
          {value}
          <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 text-gray-600 group-hover:text-teal-300" />
        </span>
      </Link>
    </li>
  );
}

/**
 * Panel de vistazo rápido del Resumen (estilo Investing, decisión de Nico
 * del 29-oct-2026): solo datos reales y verificables que ya existen en la
 * ficha, cada fila enlazada a su sección. Sin veredicto técnico tipo
 * «venta fuerte» (descartado explícitamente). Una fila sin dato real no se
 * pinta: nada de relleno.
 */
export async function QuickGlancePanel({ ticker, currency, model, analysts, livePrice, shareCapital, credibility, moatScore, keyStats = null }: {
  ticker: string;
  currency: string | null | undefined;
  model: ResearchLongTermModel | null;
  analysts: AnalystTargets | null;
  livePrice: number | null;
  shareCapital: ShareCapital | null;
  credibility: ManagementCredibility | null;
  moatScore: MoatScoreMetric | null;
  keyStats?: KeyStats | null;
}) {
  const t = await getT();
  const tk = encodeURIComponent(ticker);
  const rows: React.ReactNode[] = [];

  // Valor del modelo propio: etiquetado como precio del modelo con su
  // periodo de datos, nunca como consenso de mercado (regla de la ficha).
  const baseValuation = model && model.status !== 'not_generated' && model.publishable
    ? model.scenarios?.base?.valuation?.value_per_share ?? null
    : null;
  if (baseValuation !== null && Number.isFinite(baseValuation)) {
    rows.push(
      <Row
        href={`/research/${tk}?view=valoracion#modelo`}
        key="modelo"
        label={model?.as_of_period ? t('research.glance.modelValueWithPeriod', { period: model.as_of_period }) : t('research.glance.modelValue')}
        value={currency ? formatPrice(baseValuation, currency) : formatNumber(baseValuation)}
      />,
    );
  }

  // Consenso de analistas (agregado de Yahoo, ya presente en la cabecera):
  // mediana y recorrido contra el precio en vivo de la cabecera.
  const median = analysts?.status === 'available' ? analysts.consensus?.median ?? null : null;
  if (median !== null && Number.isFinite(median)) {
    const recorrido = livePrice !== null && livePrice > 0 ? (median - livePrice) / livePrice : null;
    rows.push(
      <Row
        href="#analistas"
        key="analistas"
        label={t('research.glance.analystsLabel')}
        note={recorrido !== null ? t('research.glance.medianUpside', { pct: formatPercent(recorrido, { digits: 1, signDisplay: 'always' }) }) : undefined}
        value={t('research.glance.medianValue', { price: analysts?.currency ? formatPrice(median, analysts.currency) : formatNumber(median) })}
      />,
    );
  }

  // Datos clave estilo Stock Analysis (REA, 31-oct-2026): solo con dato real
  // de una fuente gratuita; cada nota dice de dónde sale.
  const earnings = keyStats?.next_earnings ?? null;
  if (earnings) {
    const status = earnings.confirmed === true ? t('research.glance.earningsConfirmed')
      : earnings.confirmed === false ? t('research.glance.earningsEstimated') : undefined;
    rows.push(<Row key="resultados" label={t('research.glance.earningsLabel')} note={status} value={formatMarketDate(earnings.date)} />);
  }
  const exDividend = keyStats?.ex_dividend ?? null;
  if (exDividend) {
    rows.push(
      <Row
        key="exdividendo"
        label={exDividend.upcoming ? t('research.glance.exDividendNext') : t('research.glance.exDividendLast')}
        note={undefined}
        value={formatMarketDate(exDividend.date)}
      />,
    );
  }
  const range = keyStats?.range_52w ?? null;
  const rangeCurrency = keyStats?.currency ?? currency ?? null;
  if (range) {
    const fmt = (value: number) => (rangeCurrency ? formatPrice(value, rangeCurrency) : formatNumber(value));
    rows.push(
      <Row
        key="rango52"
        label={t('research.glance.range52wLabel')}
        note={range.source.startsWith('Yahoo') ? undefined : t('research.glance.sourceOwnCloses')}
        value={`${fmt(range.low)} – ${fmt(range.high)}`}
      />,
    );
  }
  const beta = keyStats?.beta ?? null;
  if (beta) {
    rows.push(
      <Row
        key="beta"
        label={t('research.glance.betaLabel')}
        note={t('research.glance.betaNote')}
        value={formatNumber(beta.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      />,
    );
  }

  // Ideas rápidas verificables: recompras declaradas (SEC), compromisos de
  // la directiva y calidad financiera (marco de foso).
  if (shareCapital && shareCapital.status === 'OFICIAL') {
    const ultimaRecompra = shareCapital.annual_flows
      .filter((flow) => flow.shares_repurchased || flow.common_stock_repurchased)
      .sort((a, b) => b.date.localeCompare(a.date))[0];
    rows.push(
      <Row
        href={`/research/${tk}?view=finanzas#dilucion`}
        key="recompras"
        label={t('research.glance.buybacksLabel')}
        value={ultimaRecompra ? t('research.glance.buybackYes', { year: ultimaRecompra.date.slice(0, 4) }) : t('research.glance.buybackNone')}
      />,
    );
  }
  if (credibility) {
    const grade = Object.hasOwn(GRADE_KEYS, credibility.grade) ? t(GRADE_KEYS[credibility.grade as keyof typeof GRADE_KEYS]) : credibility.grade;
    rows.push(
      <Row
        href={`/research/${tk}?view=seguimiento#directiva`}
        key="directiva"
        label={t('research.glance.credibilityLabel')}
        note={credibility.counts.open > 0 ? (credibility.counts.open === 1 ? t('research.glance.commitmentsOpen.one', { count: credibility.counts.open }) : t('research.glance.commitmentsOpen.other', { count: credibility.counts.open })) : undefined}
        value={`${formatPercent(credibility.score, { digits: 0 })} · ${grade}`}
      />,
    );
  }
  const moatTrace = moatScore?.calculation_trace as { score?: number } | undefined;
  if (typeof moatTrace?.score === 'number') {
    rows.push(
      <Row
        href={`/research/${tk}?view=valoracion#foso`}
        key="foso"
        label={t('research.glance.moatLabel')}
        value={`${formatNumber(moatTrace.score, { maximumFractionDigits: 0 })}/100`}
      />,
    );
  }

  if (!rows.length) return null;
  return (
    <aside aria-label={t('research.glance.title')} className="h-fit rounded-xl border border-gray-800 bg-surface-1 p-4">
      <h2 className="text-sm font-semibold text-gray-200">{t('research.glance.title')}</h2>
      <ul className="mt-1">{rows}</ul>
    </aside>
  );
}
