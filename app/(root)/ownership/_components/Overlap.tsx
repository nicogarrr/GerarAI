import Link from 'next/link';

import BackendOffline from '@/components/system/BackendOffline';
import { getPortfolioOverlap } from '@/lib/actions/investors.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';

import { periodLabel } from '../../inversores/_components/format';
import { Pagination, paginate } from '../../inversores/_components/Pagination';

/** Vista "Solape con tu cartera" de Movimientos 13F: qué gestores declaran tus
 *  posiciones y qué compran varios fuera de tu cartera.
 *  Antes /inversores/solape (fusionada aquí, decisión de Nico 2026-10-20). */
export async function Overlap({ pagina, compras }: { pagina?: string; compras?: string }) {
  let data: Awaited<ReturnType<typeof getPortfolioOverlap>>;
  try { data = await getPortfolioOverlap(); }
  catch (error) {
    if (isBackendUnavailableError(error)) return <BackendOffline as="section" feature="Solape de cartera" retryHref="/ownership?vista=solape" />;
    throw error;
  }
  const paged = paginate(data.positions, pagina, 10);
  const boughtPage = paginate(data.not_owned, compras, 8);
  return <>
    <p className="text-xs text-gray-400">DERIVADO · Coincidencia por CUSIP · {data.managers_with_data} gestores con datos · {data.managers_without_data} sin datos · {data.managers_partial} parciales</p>
    <p className="text-sm text-gray-400">13F histórico, no cartera actual. Hasta 45 días de retraso; posiciones largas declaradas en EE. UU., sin opciones.</p>
    {data.message && <p className="text-sm text-gray-400">{data.message}</p>}
    <ul className="flex flex-col gap-3">
      {paged.items.map(position => <li key={position.ticker} className="rounded-xl border border-gray-800 p-4">
        <Link href={`/research/${encodeURIComponent(position.ticker)}`} className="font-medium text-teal-300">{position.ticker} · {position.name}</Link>
        <p className="mt-1 text-xs text-gray-500">{position.identity_source ?? 'Sin CUSIP verificado: no se puede cruzar.'}</p>
        {position.status === 'sin_coincidencias' && <p className="mt-2 text-sm text-gray-400">Sin coincidencias en los informes disponibles.</p>}
        <ul className="mt-2 flex flex-col gap-2">
          {position.holders.map(holder => <li key={holder.slug} className="text-sm">
            <Link className="text-teal-300" href={`/inversores/${holder.slug}`}>{holder.name}</Link>
            {' · '}Cartera a {periodLabel(holder.report_date)}
            {' · '}Presentado {holder.filing_date ? periodLabel(holder.filing_date) : 'sin fecha registrada'}
            {holder.coverage === 'partial' && <span className="text-amber-300"> · Datos parciales</span>}
            {holder.filing_url && <a className="ml-2 text-teal-300" href={holder.filing_url} target="_blank" rel="noreferrer">13F original</a>}
          </li>)}
        </ul>
      </li>)}
    </ul>
    <Pagination basePath="/ownership" page={paged.page} total={paged.total} params={{ vista: 'solape', compras: compras ?? '1' }} />
    <section className="flex flex-col gap-3">
      <h2 className="text-xl font-semibold">Compradas por varios, fuera de tu cartera</h2>
      {data.unresolved_positions > 0 ? <p className="text-sm text-amber-300">Sin comparación completa: {data.unresolved_positions} posiciones sin CUSIP verificado.</p> : data.not_owned.length === 0 ? <p className="text-sm text-gray-400">Sin coincidencias con compras de dos o más gestores.</p> :
        <ul className="grid gap-3 sm:grid-cols-2">{boughtPage.items.map(item => <li key={item.cusip} className="rounded-xl border border-gray-800 p-4">
          <p className="font-medium">{item.name_of_issuer}</p><p className="text-xs text-gray-500">CUSIP {item.cusip} · {item.buyers_count} compradores</p>
          <ul className="mt-2 text-sm">{item.buyers.map(buyer => <li key={buyer.slug}><Link className="text-teal-300" href={`/inversores/${buyer.slug}`}>{buyer.name}</Link>{buyer.report_date ? ` · ${periodLabel(buyer.report_date)}` : ' · Periodo sin registrar'}</li>)}</ul>
        </li>)}</ul>}
      {boughtPage.total > 1 && <nav aria-label="Paginación de compras" className="flex justify-between gap-3 text-sm text-teal-300">
        {boughtPage.page > 1 ? <Link href={`/ownership?vista=solape&pagina=${paged.page}&compras=${boughtPage.page - 1}`}>Anterior</Link> : <span className="text-gray-500">Anterior</span>}
        <span className="text-gray-400">Página {boughtPage.page} de {boughtPage.total}</span>
        {boughtPage.page < boughtPage.total ? <Link href={`/ownership?vista=solape&pagina=${paged.page}&compras=${boughtPage.page + 1}`}>Siguiente</Link> : <span className="text-gray-500">Siguiente</span>}
      </nav>}
      {data.report_dates.length > 0 && <p className="text-xs text-gray-500">Periodos 13F: {data.report_dates.map((date) => periodLabel(date)).join(' · ')}</p>}
    </section>
  </>;
}
