'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { getValuationSummaries } from '@/lib/actions/valuation-summary.actions';
import { safetyMargin, type HealthEvidence, type ValuationSummary } from '@/lib/research/valuation-summary';
import { formatMarketDate, formatPercent, formatPrice, isValidCurrencyCode } from '@/lib/format';

export type SummaryQuote = { symbol: string; price: number | null; currency: string | null };

function Evidence({ evidence }: { evidence: HealthEvidence[] }) {
  return <ul className="mt-1 space-y-1 text-xs text-gray-400">{evidence.map(f => <li key={f.fact_id}>
    {f.source_url.startsWith('https://') ? <a className="underline" href={f.source_url} target="_blank" rel="noopener noreferrer">{f.metric}: {f.value.toLocaleString('es-ES')} {f.unit}</a> : f.metric}
    {' · '}{formatMarketDate(f.period_end)}{' · '}{f.source_type}{' · '}hecho {f.fact_id}
  </li>)}</ul>;
}

export function ValuationSummaryCard({ item, quote }: { item: ValuationSummary; quote: SummaryQuote }) {
  const fair = item.fair_value;
  const margin = safetyMargin(quote.price, quote.currency, fair);
  const health = item.health;
  const p = health.piotroski;
  const z = health.altman;
  const r = item.reverse_dcf;
  return <article className="min-w-0 rounded-xl border border-gray-800 bg-gray-900/40 p-4">
    <h3 className="font-semibold text-gray-100"><Link className="underline decoration-gray-700 underline-offset-4" href={`/research/${encodeURIComponent(item.ticker)}`}>{item.ticker}</Link></h3>
    <dl className="mt-3 space-y-3 text-sm">
      <div><dt className="text-gray-400">Valor justo</dt><dd className="text-gray-100">{fair.value != null && fair.currency && isValidCurrencyCode(fair.currency) ? formatPrice(fair.value, fair.currency) : 'No evaluable'}</dd>
        <dd className="text-xs text-gray-400">{fair.label}{fair.as_of ? ` · ${formatMarketDate(fair.as_of)}` : ''}{fair.stale ? ' · Revisar antigüedad' : ''}</dd></div>
      <div><dt className="text-gray-400">Margen de seguridad</dt><dd className="text-gray-100">{margin === null ? 'No evaluable' : formatPercent(margin)}</dd><dd className="text-xs text-gray-500">(Valor justo − precio) / valor justo. Solo misma divisa y valor publicable.</dd></div>
      <div><dt className="text-gray-400">DCF inverso: crecimiento exigido</dt><dd className="text-gray-100">{r.status === 'ok' && r.required_revenue_growth != null ? `${formatPercent(r.required_revenue_growth)} anual` : 'No evaluable'}</dd>
        {r.as_of ? <dd className="text-xs text-gray-400">{r.source} · {formatMarketDate(r.as_of)}{r.market_price != null && fair.currency && isValidCurrencyCode(fair.currency) ? ` · precio del modelo ${formatPrice(r.market_price, fair.currency)}` : ''}. Escenario separado de la tesis; no es una previsión.</dd> : null}</div>
      <div><dt className="text-gray-400">Salud financiera · Piotroski</dt><dd className="text-gray-100">{p.score == null ? `No evaluable (${p.evaluated}/9 puntos con datos)` : `${p.score}/9`}</dd>
        <dd className="text-xs text-gray-400">{health.period_end ? `Ejercicio cerrado ${formatMarketDate(health.period_end)}` : health.reason}</dd></div>
    </dl>
    <details className="mt-3 text-xs text-gray-400"><summary className="min-h-8 cursor-pointer py-1 text-teal-300">Ver puntos, fuentes y Altman Z&apos;&apos;</summary>
      {health.reason ? <p className="my-2">{health.reason}</p> : null}
      <ul className="space-y-3">{p.signals.map(signal => <li key={signal.id} className="border-t border-gray-800 pt-2"><p className="text-gray-200">{signal.label}: {signal.point ?? 'No evaluable'}</p><p className="mt-1 break-words">{signal.formula}</p>{signal.missing_input ? <p>Dato pendiente: {signal.missing_input}</p> : null}<Evidence evidence={signal.evidence} /></li>)}</ul>
      <p className="mt-3">Altman Z&apos;&apos;: {z.score == null ? 'No evaluable' : z.score.toLocaleString('es-ES', { maximumFractionDigits: 2 })}. Patrimonio contable, sin ajuste de mercados emergentes.</p>
      {z.reason ? <p>Dato pendiente: {z.reason}</p> : null}<Evidence evidence={z.evidence ?? []} />
      <p className="mt-2">{health.notice} El beneficio es el neto reportado; no se reconstruyen partidas extraordinarias ausentes.</p>
      <p className="mt-2 flex flex-wrap gap-3"><a className="underline" target="_blank" rel="noopener noreferrer" href={p.methodology_url}>Método Piotroski</a><a className="underline" target="_blank" rel="noopener noreferrer" href={z.methodology_url}>Método Altman</a></p>
    </details>
  </article>;
}

/** Same compact reading in portfolio, watchlist and discovery. One batch, no new model. */
export default function ValuationSummaryGrid({ quotes }: { quotes: SummaryQuote[] }) {
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
  return <section aria-label="Valoración y salud financiera" className="min-w-0 space-y-3">
    <h2 className="text-lg font-semibold text-gray-100">Valoración y salud financiera</h2>
    {!current ? <p role="status" className="text-sm text-gray-400">Cargando valoraciones guardadas…</p> : current.failed ? <p className="text-sm text-gray-400">La valoración no está disponible ahora. Las posiciones y los precios no cambian.</p> : <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">{Object.values(current.items).map(item => <ValuationSummaryCard key={item.ticker} item={item} quote={quotes.find(q => q.symbol.toUpperCase() === item.ticker) ?? { symbol: item.ticker, price: null, currency: null }} />)}{Object.keys(current.items).length === 0 ? <p className="text-sm text-gray-400">Sin empresas con datos de valoración guardados.</p> : null}</div>}
  </section>;
}
