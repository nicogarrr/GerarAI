import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getPublicShorts, refreshPublicShorts } from '@/lib/actions/public-shorts.actions';
import { getFormat, getT } from '@/lib/i18n/server';
import { shortsText } from '@/lib/research/shorts-text';
import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { Panel } from '@/components/ui/panel';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('research.publicShorts.metaTitle'), description: t('research.publicShorts.metaDescription') };
}

// Textos en research.publicShorts.* (es y en): «DERIVADO»/«OFICIAL», «Fecha de posición»,
// «Fecha de negociación», «Sin notificaciones…» y «Páginas de posiciones» siguen en es.
export default async function ShortsPage({ params, searchParams }: { params: Promise<{ ticker: string }>; searchParams: Promise<{ page?: string }> }) {
  await requireAuthenticatedUser();
  const t = await getT();
  const { formatMarketDate, formatNumber, formatUserDateTime, na: NA, locale } = await getFormat();
  const ticker = (await params).ticker.toUpperCase();
  const query = await searchParams;
  const result = await getPublicShorts(ticker).catch(() => null);
  const data = result?.data;
  const rows = data?.positions ?? [];
  const pages = Math.max(1, Math.ceil(rows.length / 10));
  const page = Math.min(pages, Math.max(1, Number.parseInt(query.page ?? '1', 10) || 1));
  const official = t('research.publicShorts.official');
  const derived = t('research.publicShorts.derived');
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
    <PageHeader title={t('research.publicShorts.title', { ticker })} back={<Link className="inline-flex min-h-[44px] items-center text-teal-300 sm:min-h-0" href={`/research/${encodeURIComponent(ticker)}`}>{t('research.publicShorts.back')}</Link>}
      actions={<MutationForm action={refreshPublicShorts.bind(null, ticker)} successMessage={t('research.publicShorts.refreshDone')}><Button type="submit">{t('research.publicShorts.refresh')}</Button></MutationForm>} />
    <Panel title={data?.source ?? t('research.publicShorts.noData')}>
      {!result ? <p>{t('research.publicShorts.readError')}</p> : <>
        <p className="mb-3 text-sm text-gray-400">{t('research.publicShorts.lastLookup', { date: result.fetched_at ? formatUserDateTime(result.fetched_at) : NA })}</p>
        {result.reason && <p role="status" className="mb-3 text-amber-300">{shortsText(result.reason, locale)}</p>}
        {data && <>
          <p className="mb-4 text-sm text-gray-400">{shortsText(data.note, locale)}</p>
          <a href={data.source_url} target="_blank" rel="noopener noreferrer" className="text-teal-300">{t('research.publicShorts.officialSource', { source: data.source })}</a>
          {data.source === 'CNMV' ? <>
            <p className="my-4 text-2xl">{t('research.publicShorts.publicTotal', { percent: data.public_total_percent == null ? NA : `${formatNumber(data.public_total_percent, { maximumFractionDigits: 2 })}%` })} <span className="text-xs text-gray-400">{derived}</span></p>
            {!rows.length ? <p>{t('research.publicShorts.noNotifications')}</p> : <ul className="mt-3 space-y-3">{rows.slice((page - 1) * 10, page * 10).map(row => <li className="rounded border border-gray-800 p-3" key={row.holder}><h2>{row.holder}</h2><p>{formatNumber(row.percent, { maximumFractionDigits: 2 })}% · {official} · {t('research.publicShorts.positionDate', { date: formatMarketDate(row.position_date) })}</p></li>)}</ul>}
            <nav aria-label={t('research.publicShorts.pagesLabel')} className="mt-4 flex gap-4">{page > 1 && <Link className="text-teal-300" href={`?page=${page - 1}`}>{t('research.publicShorts.previous')}</Link>}<span>{page} / {pages}</span>{page < pages && <Link className="text-teal-300" href={`?page=${page + 1}`}>{t('research.publicShorts.next')}</Link>}</nav>
          </> : <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            <div><dt>{t('research.publicShorts.tradeDate')}</dt><dd>{data.date ? formatMarketDate(data.date) : NA}</dd></div>
            <div><dt>{t('research.publicShorts.shortRatio')}</dt><dd>{data.short_volume_ratio == null ? NA : `${formatNumber(data.short_volume_ratio * 100, { maximumFractionDigits: 2 })}%`} · {derived}</dd></div>
            <div><dt>{t('research.publicShorts.shortVolume')}</dt><dd>{data.short_volume == null ? NA : formatNumber(data.short_volume, { maximumFractionDigits: 0 })}</dd></div>
            <div><dt>{t('research.publicShorts.finraVolume')}</dt><dd>{data.total_volume == null ? NA : formatNumber(data.total_volume, { maximumFractionDigits: 0 })}</dd></div>
          </dl>}
        </>}
      </>}
    </Panel>
  </main>;
}
