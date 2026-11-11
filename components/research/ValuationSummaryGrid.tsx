'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { getValuationSummaries } from '@/lib/actions/valuation-summary.actions';
import { baseRateReach, baseRateText, healthMissingLabel, piotroskiSignalText, safetyMargin, valuationSummaryText, type HealthEvidence, type ValuationSummary } from '@/lib/research/valuation-summary';
import { isValidCurrencyCode } from '@/lib/format';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import { intlLocale } from '@/lib/i18n/locale';
import { metricLabel } from '@/lib/research/metric-labels';

export type SummaryQuote = { symbol: string; price: number | null; currency: string | null };

function Evidence({ evidence }: { evidence: HealthEvidence[] }) {
  const t = useT();
  const locale = useLocale();
  const { formatMarketDate } = useFormat();
  return <ul className="mt-1 space-y-1 text-xs text-gray-400">{evidence.map(f => <li key={f.fact_id}>
    {f.source_url.startsWith('https://') ? <a className="underline" href={f.source_url} target="_blank" rel="noopener noreferrer">{metricLabel(f.metric)}: {f.value.toLocaleString(intlLocale(locale))} {f.unit}</a> : metricLabel(f.metric)}
    {' · '}{formatMarketDate(f.period_end)}{' · '}{f.source_type}{' · '}{t('researchShared.valuationSummary.fact', { id: f.fact_id })}
  </li>)}</ul>;
}

const REACH_KEYS = {
  reachEq: 'researchShared.valuationSummary.reachEq',
  reachLt: 'researchShared.valuationSummary.reachLt',
  reachGt: 'researchShared.valuationSummary.reachGt',
} as const;

export function ValuationSummaryCard({ item, quote }: { item: ValuationSummary; quote: SummaryQuote }) {
  const t = useT();
  const locale = useLocale();
  const { formatMarketDate, formatPercent, formatPrice } = useFormat();
  const na = t('researchShared.valuationSummary.notEvaluable');
  const fair = item.fair_value;
  const margin = safetyMargin(quote.price, quote.currency, fair);
  const health = item.health;
  const p = health.piotroski;
  const z = health.altman;
  const r = item.reverse_dcf;
  const baseRate = baseRateText(item.base_rate, locale);
  const reach = baseRateReach(r.base_rate_check);
  return <article className="min-w-0 rounded-xl border border-gray-800 bg-gray-900/40 p-4">
    <h3 className="font-semibold text-gray-100"><Link className="inline-flex min-h-[44px] items-center underline decoration-gray-700 underline-offset-4" href={`/research/${encodeURIComponent(item.ticker)}`}>{item.ticker}</Link></h3>
    <dl className="mt-3 space-y-3 text-sm">
      <div><dt className="text-gray-400">{t('researchShared.valuationSummary.fairValue')}</dt><dd className="text-gray-100">{fair.value != null && fair.currency && isValidCurrencyCode(fair.currency) ? formatPrice(fair.value, fair.currency) : na}</dd>
        <dd className="text-xs text-gray-400">{valuationSummaryText(fair.label, locale)}{fair.as_of ? ` · ${formatMarketDate(fair.as_of)}` : ''}{fair.stale ? ` · ${t('researchShared.valuationSummary.reviewAge')}` : ''}</dd>
        {fair.value == null && fair.reason ? <dd className="text-xs text-gray-400">{valuationSummaryText(fair.reason, locale)}</dd> : null}
        {baseRate ? <dd className="text-xs text-gray-500">{baseRate}</dd> : null}</div>
      <div><dt className="text-gray-400">{t('researchShared.valuationSummary.margin')}</dt><dd className="text-gray-100">{margin === null ? na : formatPercent(margin)}</dd></div>
      <div><dt className="text-gray-400">{t('researchShared.valuationSummary.reverseDcf')}</dt><dd className="text-gray-100">{r.status === 'ok' && r.required_revenue_growth != null ? t('researchShared.valuationSummary.perYear', { pct: formatPercent(r.required_revenue_growth) }) : na}</dd>
        {r.as_of ? <dd className="text-xs text-gray-400">{valuationSummaryText(r.source, locale)} · {formatMarketDate(r.as_of)}{r.market_price != null && fair.currency && isValidCurrencyCode(fair.currency) ? t('researchShared.valuationSummary.modelPrice', { price: formatPrice(r.market_price, fair.currency) }) : ''}. {t('researchShared.valuationSummary.scenarioNote')}</dd> : null}
        {r.status !== 'ok' && r.reason ? <dd className="text-xs text-gray-400">{valuationSummaryText(r.reason, locale)}</dd> : null}
        {r.status === 'ok' && reach ? <dd className="text-xs text-gray-500" title={r.base_rate_check?.formula ?? undefined} data-testid="reverse-dcf-base-rate-reach">{t(REACH_KEYS[reach.key], { pct: formatPercent(reach.share, { digits: 0 }), years: r.base_rate_check?.horizon_years ?? '' })}</dd> : null}</div>
      <div><dt className="text-gray-400">{t('researchShared.valuationSummary.piotroski')}</dt><dd className="text-gray-100">{p.score == null ? t('researchShared.valuationSummary.piotroskiPartial', { count: p.evaluated }) : p.partial ? t('researchShared.valuationSummary.piotroskiPartialScore', { score: p.score, count: p.evaluated }) : `${p.score}/9`}</dd>
        <dd className="text-xs text-gray-400">{health.period_end ? t('researchShared.valuationSummary.fiscalYear', { date: formatMarketDate(health.period_end) }) : valuationSummaryText(health.reason ?? '', locale)}</dd></div>
    </dl>
    <details className="mt-3 text-xs text-gray-400"><summary className="min-h-[44px] cursor-pointer py-3 text-teal-300">{t('researchShared.valuationSummary.details')}</summary>
      {health.reason ? <p className="my-2">{valuationSummaryText(health.reason, locale)}</p> : null}
      <ul className="space-y-3">{p.signals.map(signal => <li key={signal.id} className="border-t border-gray-800 pt-2"><p className="text-gray-200">{piotroskiSignalText(signal, locale).label}: {signal.point ?? na}</p><p className="mt-1 break-words">{piotroskiSignalText(signal, locale).formula}</p>{signal.missing_input ? <p>{t('researchShared.valuationSummary.pending', { item: healthMissingLabel(signal.missing_input, locale) })}</p> : null}<Evidence evidence={signal.evidence} /></li>)}</ul>
      <p className="mt-3">Altman Z: {z.score == null ? na : z.score.toLocaleString(intlLocale(locale), { maximumFractionDigits: 2 })}. {t('researchShared.valuationSummary.altmanNote')}</p>
      {z.reason ? <p>{t('researchShared.valuationSummary.pending', { item: healthMissingLabel(z.reason, locale) })}</p> : null}<Evidence evidence={z.evidence ?? []} />
      <p className="mt-2">{valuationSummaryText(health.notice, locale)} {t('researchShared.valuationSummary.profitNote')}</p>
      <p className="mt-2 flex flex-wrap gap-x-4"><a className="inline-flex min-h-[44px] items-center underline" target="_blank" rel="noopener noreferrer" href={p.methodology_url}>{t('researchShared.valuationSummary.piotroskiMethod')}</a><a className="inline-flex min-h-[44px] items-center underline" target="_blank" rel="noopener noreferrer" href={z.methodology_url}>{t('researchShared.valuationSummary.altmanMethod')}</a></p>
    </details>
  </article>;
}

/** Same compact reading in portfolio, watchlist and discovery. One batch, no new model. */
export default function ValuationSummaryGrid({ quotes }: { quotes: SummaryQuote[] }) {
  const t = useT();
  const key = [...new Set(quotes.map(q => q.symbol.toUpperCase()))].sort().slice(0, 60).join(',');
  const [loaded, setLoaded] = useState<{ key: string; items: Record<string, ValuationSummary>; failed: boolean } | null>(null);
  useEffect(() => {
    if (!key) return;
    let active = true;
    getValuationSummaries(key.split(',')).then(items => { if (active) setLoaded({ key, items, failed: false }); })
      .catch(() => { if (active) setLoaded({ key, items: {}, failed: true }); });
    return () => { active = false; };
  }, [key]);
  if (!key) return null;
  const current = loaded?.key === key ? loaded : null;
  return <section aria-label={t('researchShared.valuationSummary.title')} className="min-w-0 space-y-3">
    <h2 className="text-lg font-semibold text-gray-100">{t('researchShared.valuationSummary.title')}</h2>
    {/* La formula del margen se explica una vez por seccion: antes iba en cada
        tarjeta y se repetia tantas veces como empresas (6+ en cartera). */}
    <p className="text-xs text-gray-500">{t('researchShared.valuationSummary.marginHelp')}</p>
    {!current ? <p role="status" className="text-sm text-gray-400">{t('researchShared.valuationSummary.loading')}</p> : current.failed ? <p className="text-sm text-gray-400">{t('researchShared.valuationSummary.failed')}</p> : <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">{Object.values(current.items).map(item => <ValuationSummaryCard key={item.ticker} item={item} quote={quotes.find(q => q.symbol.toUpperCase() === item.ticker) ?? { symbol: item.ticker, price: null, currency: null }} />)}{Object.keys(current.items).length === 0 ? <p className="text-sm text-gray-400">{t('researchShared.valuationSummary.empty')}</p> : null}</div>}
  </section>;
}
