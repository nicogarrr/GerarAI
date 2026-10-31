'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import type { CapitalFact, ShareCapital } from '@/lib/actions/share-capital.actions';
import { formatCompact, formatMarketDate, formatNumber } from '@/lib/format';
import { Panel } from '@/components/ui/panel';
import { Stat } from '@/components/ui/stat';

// recharts (~120 KB gzip con sus d3) solo sirve para la gráfica de evolución:
// se carga diferida y el panel (stats + tabla) pinta sin ella. El esqueleto
// reserva el mismo h-64 del contenedor: no hay salto de layout al llegar.
const ShareCapitalChart = dynamic(() => import('@/components/research/ShareCapitalChart'), {
  loading: () => <div className="h-full w-full animate-pulse rounded bg-slate-800/40" aria-hidden="true" />,
});

const compact = (value: number) => formatCompact(value);
const percent = (value: number | null) => value == null ? 'N/D' : `${value > 0 ? '+' : ''}${formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
function Source({ fact }: { fact: CapitalFact }) {
  return <a href={fact.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-teal-300">{fact.source} · {formatMarketDate(fact.date)}{fact.reported_on ? ` · Presentado ${formatMarketDate(fact.reported_on)}` : ''}</a>;
}
function Fact({ fact }: { fact?: CapitalFact }) {
  return fact ? <div><div>{compact(fact.value)}{fact.unit && fact.unit !== 'shares' ? ` ${fact.unit}` : ''}</div><Source fact={fact} /></div> : <span className="text-gray-500">N/D</span>;
}
function Pager({ page, pages, onChange }: { page: number; pages: number; onChange: (value: number) => void }) {
  return <nav aria-label="Páginas de capital" className="flex items-center justify-between gap-4 text-sm">
    <button className="text-teal-300 disabled:text-gray-600" disabled={page === 1} onClick={() => onChange(page - 1)}>Anterior</button>
    <span>{page} / {pages}</span>
    <button className="text-teal-300 disabled:text-gray-600" disabled={page === pages} onClick={() => onChange(page + 1)}>Siguiente</button>
  </nav>;
}
export function ShareCapitalPanel({ data }: { data: ShareCapital }) {
  const [tab, setTab] = useState<'balances' | 'flows'>('balances');
  const [page, setPage] = useState(1);
  const latest = data.series.at(-1);
  const count = tab === 'balances' ? data.series.length : data.annual_flows.length;
  const pages = Math.max(1, Math.ceil(count / 10));
  return <>
    <div className="grid gap-3 sm:grid-cols-2">
      <Stat label="Acciones en circulación" value={latest ? compact(latest.value) : 'N/D'} hint={latest ? <Source fact={latest} /> : 'Sin saldo de acciones con fuente verificable'} />
      <Stat label="Cambio neto entre balances" value={percent(latest?.net_change_pct ?? null)} hint={latest?.net_change_pct != null ? `Calculado · ${formatMarketDate(latest.previous_date)} → ${formatMarketDate(latest.date)}` : latest?.split_between_dates ? 'Split entre fechas · no comparable' : latest?.abrupt_jump ? 'Salto brusco · posible split no registrado · no comparable' : 'Sin dos balances comparables'} />
    </div>
    <p className="text-xs text-gray-400">Saldos sin ajustar por splits. El cambio neto no identifica emisiones ni recompras.</p>
    {data.series.length > 1 && <Panel title="Evolución de acciones · OFICIAL">
      <div className="h-64 min-w-0" role="img" aria-label="Evolución de los saldos de acciones publicados; cifras exactas en la tabla de saldos">
        <ShareCapitalChart series={data.series} />
      </div>
    </Panel>}
    <Panel title="Historial">
      <div role="group" aria-label="Tipo de historial" className="mb-4 flex gap-4 text-sm">
        <button aria-pressed={tab === 'balances'} className={`inline-flex min-h-[44px] items-center sm:min-h-0 ${tab === 'balances' ? 'text-teal-300' : 'text-gray-400'}`} onClick={() => { setTab('balances'); setPage(1); }}>Saldos</button>
        <button aria-pressed={tab === 'flows'} className={`inline-flex min-h-[44px] items-center sm:min-h-0 ${tab === 'flows' ? 'text-teal-300' : 'text-gray-400'}`} onClick={() => { setTab('flows'); setPage(1); }}>Emisiones y recompras anuales</button>
      </div>
      {!count ? <p className="text-sm text-gray-400">No hay {tab === 'balances' ? 'saldos de acciones' : 'flujos anuales'} con fuente verificable.</p> : <>
        <Pager page={page} pages={pages} onChange={setPage} />
        <div aria-label="Historial de capital" className="my-4 overflow-x-auto" role="region" tabIndex={0}>
          {tab === 'balances' ? <table className="w-full text-left text-sm"><caption className="sr-only">Saldos de acciones en circulación por fecha y fuente, con el cambio neto derivado entre balances</caption><thead><tr className="text-gray-400"><th className="p-2" scope="col">Fecha / fuente</th><th className="p-2" scope="col">Acciones</th><th className="p-2" scope="col">Cambio neto · DERIVADO</th></tr></thead>
            <tbody>{[...data.series].reverse().slice((page - 1) * 10, page * 10).map(row => <tr className="border-t border-gray-800" key={row.date}><th className="p-2 text-left font-normal" scope="row"><Source fact={row} /></th><td className="p-2">{compact(row.value)}</td><td className="p-2">{row.split_between_dates ? 'Split · no comparable' : row.abrupt_jump ? 'Salto brusco · posible split no registrado · no comparable' : percent(row.net_change_pct)}{row.previous_date && <div className="text-xs text-gray-500">Desde {formatMarketDate(row.previous_date)}</div>}</td></tr>)}</tbody>
          </table> : <table className="w-full min-w-[640px] text-left text-sm"><caption className="sr-only">Emisiones y recompras anuales: cierre de acciones, recompras, acciones recompradas, emisiones y compensación en acciones</caption><thead><tr className="text-gray-400"><th className="p-2" scope="col">Cierre</th><th className="p-2" scope="col">Recompras</th><th className="p-2" scope="col">Acciones recompradas</th><th className="p-2" scope="col">Emisiones</th><th className="p-2" scope="col">Compensación en acciones</th></tr></thead>
            <tbody>{[...data.annual_flows].reverse().slice((page - 1) * 10, page * 10).map(row => <tr className="border-t border-gray-800" key={row.date}><th className="p-2 text-left font-normal" scope="row">{formatMarketDate(row.date)}</th><td className="p-2"><Fact fact={row.common_stock_repurchased} /></td><td className="p-2"><Fact fact={row.shares_repurchased} /></td><td className="p-2"><Fact fact={row.common_stock_issued} /></td><td className="p-2"><Fact fact={row.stock_based_compensation} /></td></tr>)}</tbody>
          </table>}
        </div>
        <Pager page={page} pages={pages} onChange={setPage} />
      </>}
    </Panel>
  </>;
}
