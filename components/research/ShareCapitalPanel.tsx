'use client';

import { useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { CapitalFact, ShareCapital } from '@/lib/actions/share-capital.actions';
import { formatCompact, formatNumber } from '@/lib/format';
import { Panel } from '@/components/ui/panel';
import { Stat } from '@/components/ui/stat';

const compact = (value: number) => formatCompact(value);
const percent = (value: number | null) => value == null ? 'N/D' : `${value > 0 ? '+' : ''}${formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
function Source({ fact }: { fact: CapitalFact }) {
  return <a href={fact.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-teal-300">{fact.source} · {fact.date}{fact.reported_on ? ` · Presentado ${fact.reported_on}` : ''}</a>;
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
      <Stat label="Cambio neto entre balances" value={percent(latest?.net_change_pct ?? null)} hint={latest?.net_change_pct != null ? `Calculado · ${latest.previous_date} → ${latest.date}` : latest?.split_between_dates ? 'Split entre fechas · no comparable' : latest?.abrupt_jump ? 'Salto brusco · posible split no registrado · no comparable' : 'Sin dos balances comparables'} />
    </div>
    <p className="text-xs text-gray-400">Saldos sin ajustar por splits. El cambio neto no identifica emisiones ni recompras.</p>
    {data.series.length > 1 && <Panel title="Evolución de acciones · OFICIAL">
      <div className="h-64 min-w-0" role="img" aria-label="Evolución de los saldos de acciones publicados; cifras exactas en la tabla de saldos">
        <ResponsiveContainer width="100%" height="100%"><LineChart data={data.series} margin={{ left: 8, right: 16, top: 10, bottom: 10 }}>
          <CartesianGrid stroke="#374151" strokeDasharray="3 3" /><XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9ca3af' }} minTickGap={32} />
          <YAxis tickFormatter={compact} tick={{ fontSize: 10, fill: '#9ca3af' }} width={65} domain={['auto', 'auto']} />
          <Tooltip formatter={(value) => [compact(Number(value)), 'Acciones']} contentStyle={{ background: '#111827', border: '1px solid #374151', color: '#f3f4f6' }} />
          <Line type="linear" dataKey="value" stroke="#2dd4bf" dot={false} strokeWidth={2} isAnimationActive={false} />
        </LineChart></ResponsiveContainer>
      </div>
    </Panel>}
    <Panel title="Historial">
      <div role="group" aria-label="Tipo de historial" className="mb-4 flex gap-4 text-sm">
        <button aria-pressed={tab === 'balances'} className={tab === 'balances' ? 'text-teal-300' : 'text-gray-400'} onClick={() => { setTab('balances'); setPage(1); }}>Saldos</button>
        <button aria-pressed={tab === 'flows'} className={tab === 'flows' ? 'text-teal-300' : 'text-gray-400'} onClick={() => { setTab('flows'); setPage(1); }}>Emisiones y recompras anuales</button>
      </div>
      {!count ? <p className="text-sm text-gray-400">No hay {tab === 'balances' ? 'saldos de acciones' : 'flujos anuales'} con fuente verificable.</p> : <>
        <Pager page={page} pages={pages} onChange={setPage} />
        <div className="my-4 overflow-x-auto">
          {tab === 'balances' ? <table className="w-full text-left text-sm"><thead><tr className="text-gray-400"><th className="p-2">Fecha / fuente</th><th className="p-2">Acciones</th><th className="p-2">Cambio neto · DERIVADO</th></tr></thead>
            <tbody>{[...data.series].reverse().slice((page - 1) * 10, page * 10).map(row => <tr className="border-t border-gray-800" key={row.date}><td className="p-2"><Source fact={row} /></td><td className="p-2">{compact(row.value)}</td><td className="p-2">{row.split_between_dates ? 'Split · no comparable' : row.abrupt_jump ? 'Salto brusco · posible split no registrado · no comparable' : percent(row.net_change_pct)}{row.previous_date && <div className="text-xs text-gray-500">Desde {row.previous_date}</div>}</td></tr>)}</tbody>
          </table> : <table className="w-full min-w-[640px] text-left text-sm"><thead><tr className="text-gray-400"><th className="p-2">Cierre</th><th className="p-2">Recompras</th><th className="p-2">Acciones recompradas</th><th className="p-2">Emisiones</th><th className="p-2">Compensación en acciones</th></tr></thead>
            <tbody>{[...data.annual_flows].reverse().slice((page - 1) * 10, page * 10).map(row => <tr className="border-t border-gray-800" key={row.date}><td className="p-2">{row.date}</td><td className="p-2"><Fact fact={row.common_stock_repurchased} /></td><td className="p-2"><Fact fact={row.shares_repurchased} /></td><td className="p-2"><Fact fact={row.common_stock_issued} /></td><td className="p-2"><Fact fact={row.stock_based_compensation} /></td></tr>)}</tbody>
          </table>}
        </div>
        <Pager page={page} pages={pages} onChange={setPage} />
      </>}
    </Panel>
  </>;
}
