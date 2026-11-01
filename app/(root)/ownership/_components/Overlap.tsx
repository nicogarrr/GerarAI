import Link from 'next/link';

import BackendOffline from '@/components/system/BackendOffline';
import { getPortfolioOverlap } from '@/lib/actions/investors.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getLocale, getT } from '@/lib/i18n/server';

import { periodLabel } from '../../inversores/_components/format';
import { Pagination, paginate } from '../../inversores/_components/Pagination';

/** Vista "Solape con tu cartera" de Movimientos 13F: qué gestores declaran tus
 *  posiciones y qué compran varios fuera de tu cartera.
 *  Antes /inversores/solape (fusionada aquí, decisión de Nico 2026-10-20). */
export async function Overlap({ pagina, compras }: { pagina?: string; compras?: string }) {
  const t = await getT();
  const locale = await getLocale();
  let data: Awaited<ReturnType<typeof getPortfolioOverlap>>;
  try { data = await getPortfolioOverlap(); }
  catch (error) {
    if (isBackendUnavailableError(error)) return <BackendOffline as="section" feature={t('ownership.overlap.feature')} retryHref="/ownership?vista=solape" />;
    throw error;
  }
  const paged = paginate(data.positions, pagina, 10);
  const boughtPage = paginate(data.not_owned, compras, 8);
  return <>
    <p className="text-xs text-gray-400">{t('ownership.overlap.summary', { withData: data.managers_with_data, withoutData: data.managers_without_data, partial: data.managers_partial })}</p>
    <p className="text-sm text-gray-400">{t('ownership.overlap.note')}</p>
    {data.message && <p className="text-sm text-gray-400">{data.message}</p>}
    <ul className="flex flex-col gap-3">
      {paged.items.map(position => <li key={position.ticker} className="rounded-xl border border-gray-800 p-4">
        <Link href={`/research/${encodeURIComponent(position.ticker)}`} className="font-medium text-teal-300">{position.ticker} · {position.name}</Link>
        <p className="mt-1 text-xs text-gray-500">{position.identity_source ?? t('ownership.overlap.noCusip')}</p>
        {position.status === 'sin_coincidencias' && <p className="mt-2 text-sm text-gray-400">{t('ownership.overlap.noMatches')}</p>}
        <ul className="mt-2 flex flex-col gap-2">
          {position.holders.map(holder => <li key={holder.slug} className="text-sm">
            <Link className="text-teal-300" href={`/inversores/${holder.slug}`}>{holder.name}</Link>
            {' · '}{t('ownership.overlap.portfolioAt', { period: periodLabel(holder.report_date, locale) })}
            {' · '}{t('ownership.overlap.filed', { date: holder.filing_date ? periodLabel(holder.filing_date, locale) : t('ownership.overlap.noFilingDate') })}
            {holder.coverage === 'partial' && <span className="text-amber-300"> · {t('ownership.overlap.partialData')}</span>}
            {holder.filing_url && <a className="ml-2 text-teal-300" href={holder.filing_url} target="_blank" rel="noreferrer">{t('ownership.overlap.original')}</a>}
          </li>)}
        </ul>
      </li>)}
    </ul>
    <Pagination basePath="/ownership" page={paged.page} total={paged.total} params={{ vista: 'solape', compras: compras ?? '1' }} />
    <section className="flex flex-col gap-3">
      <h2 className="text-xl font-semibold">{t('ownership.overlap.boughtTitle')}</h2>
      {data.unresolved_positions > 0 ? <p className="text-sm text-amber-300">{t('ownership.overlap.unresolved', { n: data.unresolved_positions })}</p> : data.not_owned.length === 0 ? <p className="text-sm text-gray-400">{t('ownership.overlap.noBought')}</p> :
        <ul className="grid gap-3 sm:grid-cols-2">{boughtPage.items.map(item => <li key={item.cusip} className="rounded-xl border border-gray-800 p-4">
          <p className="font-medium">{item.name_of_issuer}</p><p className="text-xs text-gray-500">{t('ownership.overlap.buyers', { cusip: item.cusip, n: item.buyers_count })}</p>
          <ul className="mt-2 text-sm">{item.buyers.map(buyer => <li key={buyer.slug}><Link className="text-teal-300" href={`/inversores/${buyer.slug}`}>{buyer.name}</Link>{buyer.report_date ? ` · ${periodLabel(buyer.report_date, locale)}` : ` · ${t('ownership.overlap.noPeriod')}`}</li>)}</ul>
        </li>)}</ul>}
      {boughtPage.total > 1 && <nav aria-label={t('ownership.overlap.pagerAria')} className="flex justify-between gap-3 text-sm text-teal-300">
        {boughtPage.page > 1 ? <Link href={`/ownership?vista=solape&pagina=${paged.page}&compras=${boughtPage.page - 1}`}>{t('ownership.overlap.prev')}</Link> : <span className="text-gray-500">{t('ownership.overlap.prev')}</span>}
        <span className="text-gray-400">{t('ownership.overlap.page', { page: boughtPage.page, total: boughtPage.total })}</span>
        {boughtPage.page < boughtPage.total ? <Link href={`/ownership?vista=solape&pagina=${paged.page}&compras=${boughtPage.page + 1}`}>{t('ownership.overlap.next')}</Link> : <span className="text-gray-500">{t('ownership.overlap.next')}</span>}
      </nav>}
      {data.report_dates.length > 0 && <p className="text-xs text-gray-500">{t('ownership.overlap.periods', { periods: data.report_dates.map((date) => periodLabel(date, locale)).join(' · ') })}</p>}
    </section>
  </>;
}
