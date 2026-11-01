'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import type { CapitalFact, ShareCapital } from '@/lib/actions/share-capital.actions';
import { useFormat, useT } from '@/lib/i18n/client';
import { Panel } from '@/components/ui/panel';
import { Stat } from '@/components/ui/stat';

// recharts (~120 KB gzip con sus d3) solo sirve para la gráfica de evolución:
// se carga diferida y el panel (stats + tabla) pinta sin ella. El esqueleto
// reserva el mismo h-64 del contenedor: no hay salto de layout al llegar.
const ShareCapitalChart = dynamic(() => import('@/components/research/ShareCapitalChart'), {
  loading: () => <div className="h-full w-full animate-pulse rounded bg-slate-800/40" aria-hidden="true" />,
});

/** Cifras con el formato del idioma elegido (es-ES por defecto). */
function useNums() {
  const { formatCompact, formatNumber, na } = useFormat();
  return {
    na,
    compact: (value: number) => formatCompact(value),
    percent: (value: number | null) => value == null ? na : `${value > 0 ? '+' : ''}${formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`,
  };
}
function Source({ fact }: { fact: CapitalFact }) {
  const t = useT();
  const { formatMarketDate } = useFormat();
  return <a href={fact.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-teal-300">{fact.source} · {formatMarketDate(fact.date)}{fact.reported_on ? t('research.shareCapital.filed', { date: formatMarketDate(fact.reported_on) }) : ''}</a>;
}
function Fact({ fact }: { fact?: CapitalFact }) {
  const { compact, na } = useNums();
  return fact ? <div><div>{compact(fact.value)}{fact.unit && fact.unit !== 'shares' ? ` ${fact.unit}` : ''}</div><Source fact={fact} /></div> : <span className="text-gray-500">{na}</span>;
}
function Pager({ page, pages, onChange }: { page: number; pages: number; onChange: (value: number) => void }) {
  const t = useT();
  return <nav aria-label={t('research.shareCapital.pages')} className="flex items-center justify-between gap-4 text-sm">
    <button className="text-teal-300 disabled:text-gray-600" disabled={page === 1} onClick={() => onChange(page - 1)}>{t('research.shareCapital.prev')}</button>
    <span>{page} / {pages}</span>
    <button className="text-teal-300 disabled:text-gray-600" disabled={page === pages} onClick={() => onChange(page + 1)}>{t('research.shareCapital.next')}</button>
  </nav>;
}
export function ShareCapitalPanel({ data }: { data: ShareCapital }) {
  const [tab, setTab] = useState<'balances' | 'flows'>('balances');
  const t = useT();
  const { formatMarketDate } = useFormat();
  const { compact, percent, na } = useNums();
  const [page, setPage] = useState(1);
  const latest = data.series.at(-1);
  const count = tab === 'balances' ? data.series.length : data.annual_flows.length;
  const pages = Math.max(1, Math.ceil(count / 10));
  return <>
    <div className="grid gap-3 sm:grid-cols-2">
      <Stat label={t('research.shareCapital.outstanding')} value={latest ? compact(latest.value) : na} hint={latest ? <Source fact={latest} /> : t('research.shareCapital.noBalance')} />
      <Stat label={t('research.shareCapital.netChange')} value={percent(latest?.net_change_pct ?? null)} hint={latest?.net_change_pct != null ? t('research.shareCapital.calculated', { from: formatMarketDate(latest.previous_date), to: formatMarketDate(latest.date) }) : latest?.split_between_dates ? t('research.shareCapital.splitBetween') : latest?.abrupt_jump ? t('research.shareCapital.abruptJump') : t('research.shareCapital.noComparable')} />
    </div>
    <p className="text-xs text-gray-400">{t('research.shareCapital.unadjusted')}</p>
    {data.series.length > 1 && <Panel title={t('research.shareCapital.chartTitle')}>
      <div className="h-64 min-w-0" role="img" aria-label={t('research.shareCapital.chartLabel')}>
        <ShareCapitalChart series={data.series} />
      </div>
    </Panel>}
    <Panel title={t('research.shareCapital.history')}>
      <div role="group" aria-label={t('research.shareCapital.historyType')} className="mb-4 flex gap-4 text-sm">
        <button aria-pressed={tab === 'balances'} className={`inline-flex min-h-[44px] items-center sm:min-h-0 ${tab === 'balances' ? 'text-teal-300' : 'text-gray-400'}`} onClick={() => { setTab('balances'); setPage(1); }}>{t('research.shareCapital.balances')}</button>
        <button aria-pressed={tab === 'flows'} className={`inline-flex min-h-[44px] items-center sm:min-h-0 ${tab === 'flows' ? 'text-teal-300' : 'text-gray-400'}`} onClick={() => { setTab('flows'); setPage(1); }}>{t('research.shareCapital.flows')}</button>
      </div>
      {!count ? <p className="text-sm text-gray-400">{tab === 'balances' ? t('research.shareCapital.emptyBalances') : t('research.shareCapital.emptyFlows')}</p> : <>
        <Pager page={page} pages={pages} onChange={setPage} />
        <div aria-label={t('research.shareCapital.historyRegion')} className="my-4 overflow-x-auto" role="region" tabIndex={0}>
          {tab === 'balances' ? <table className="w-full text-left text-sm"><caption className="sr-only">{t('research.shareCapital.balancesCaption')}</caption><thead><tr className="text-gray-400"><th className="p-2" scope="col">{t('research.shareCapital.dateSource')}</th><th className="p-2" scope="col">{t('research.shareCapital.shares')}</th><th className="p-2" scope="col">{t('research.shareCapital.netChangeDerived')}</th></tr></thead>
            <tbody>{[...data.series].reverse().slice((page - 1) * 10, page * 10).map(row => <tr className="border-t border-gray-800" key={row.date}><th className="p-2 text-left font-normal" scope="row"><Source fact={row} /></th><td className="p-2">{compact(row.value)}</td><td className="p-2">{row.split_between_dates ? t('research.shareCapital.splitRow') : row.abrupt_jump ? t('research.shareCapital.abruptJump') : percent(row.net_change_pct)}{row.previous_date && <div className="text-xs text-gray-500">{t('research.shareCapital.since', { date: formatMarketDate(row.previous_date) })}</div>}</td></tr>)}</tbody>
          </table> : <table className="w-full min-w-[640px] text-left text-sm"><caption className="sr-only">{t('research.shareCapital.flowsCaption')}</caption><thead><tr className="text-gray-400"><th className="p-2" scope="col">{t('research.shareCapital.yearEnd')}</th><th className="p-2" scope="col">{t('research.shareCapital.buybacks')}</th><th className="p-2" scope="col">{t('research.shareCapital.sharesRepurchased')}</th><th className="p-2" scope="col">{t('research.shareCapital.issuances')}</th><th className="p-2" scope="col">{t('research.shareCapital.sbc')}</th></tr></thead>
            <tbody>{[...data.annual_flows].reverse().slice((page - 1) * 10, page * 10).map(row => <tr className="border-t border-gray-800" key={row.date}><th className="p-2 text-left font-normal" scope="row">{formatMarketDate(row.date)}</th><td className="p-2"><Fact fact={row.common_stock_repurchased} /></td><td className="p-2"><Fact fact={row.shares_repurchased} /></td><td className="p-2"><Fact fact={row.common_stock_issued} /></td><td className="p-2"><Fact fact={row.stock_based_compensation} /></td></tr>)}</tbody>
          </table>}
        </div>
        <Pager page={page} pages={pages} onChange={setPage} />
      </>}
    </Panel>
  </>;
}
