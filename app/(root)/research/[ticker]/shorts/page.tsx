import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getPublicShorts, refreshPublicShorts } from '@/lib/actions/public-shorts.actions';
import { formatMarketDate, formatNumber, formatUserDateTime } from '@/lib/format';
import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { Panel } from '@/components/ui/panel';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Cortos públicos',
  description: 'Posiciones cortas declaradas en registros públicos, con fecha y fuente oficiales.',
};

export default async function ShortsPage({ params, searchParams }: { params: Promise<{ ticker: string }>; searchParams: Promise<{ page?: string }> }) {
  await requireAuthenticatedUser();
  const ticker = (await params).ticker.toUpperCase();
  const query = await searchParams;
  const result = await getPublicShorts(ticker).catch(() => null);
  const data = result?.data;
  const rows = data?.positions ?? [];
  const pages = Math.max(1, Math.ceil(rows.length / 10));
  const page = Math.min(pages, Math.max(1, Number.parseInt(query.page ?? '1', 10) || 1));
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
    <PageHeader title={`Cortos públicos · ${ticker}`} back={<Link className="inline-flex min-h-[44px] items-center text-teal-300 sm:min-h-0" href={`/research/${encodeURIComponent(ticker)}`}>Volver a la empresa</Link>}
      actions={<MutationForm action={refreshPublicShorts.bind(null, ticker)} successMessage="Consulta terminada"><Button type="submit">Actualizar fuente</Button></MutationForm>} />
    <Panel title={data?.source ?? 'Sin datos'}>
      {!result ? <p>No se pudo leer la consulta almacenada. No es un recuento de cero posiciones.</p> : <>
        <p className="mb-3 text-sm text-gray-400">Última consulta con datos: {result.fetched_at ? formatUserDateTime(result.fetched_at) : 'N/D'}. Máximo una consulta por hora.</p>
        {result.reason && <p role="status" className="mb-3 text-amber-300">{result.reason}</p>}
        {data && <>
          <p className="mb-4 text-sm text-gray-400">{data.note}</p>
          <a href={data.source_url} target="_blank" rel="noopener noreferrer" className="text-teal-300">Fuente oficial · {data.source}</a>
          {data.source === 'CNMV' ? <>
            <p className="my-4 text-2xl">Suma pública: {data.public_total_percent == null ? 'N/D' : formatNumber(data.public_total_percent, { maximumFractionDigits: 2 })}% <span className="text-xs text-gray-400">DERIVADO</span></p>
            {!rows.length ? <p>Sin notificaciones en la tabla pública consultada. No implica ausencia de cortos por debajo del umbral.</p> : <ul className="mt-3 space-y-3">{rows.slice((page - 1) * 10, page * 10).map(row => <li className="rounded border border-gray-800 p-3" key={row.holder}><h2>{row.holder}</h2><p>{formatNumber(row.percent, { maximumFractionDigits: 2 })}% · OFICIAL · Fecha de posición: {formatMarketDate(row.position_date)}</p></li>)}</ul>}
            <nav aria-label="Páginas de posiciones" className="mt-4 flex gap-4">{page > 1 && <Link className="text-teal-300" href={`?page=${page - 1}`}>Anterior</Link>}<span>{page} / {pages}</span>{page < pages && <Link className="text-teal-300" href={`?page=${page + 1}`}>Siguiente</Link>}</nav>
          </> : <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            <div><dt>Fecha de negociación</dt><dd>{data.date ? formatMarketDate(data.date) : 'N/D'}</dd></div>
            <div><dt>Volumen corto / volumen FINRA</dt><dd>{data.short_volume_ratio == null ? 'N/D' : `${formatNumber(data.short_volume_ratio * 100, { maximumFractionDigits: 2 })}%`} · DERIVADO</dd></div>
            <div><dt>Volumen corto · OFICIAL</dt><dd>{data.short_volume == null ? 'N/D' : formatNumber(data.short_volume, { maximumFractionDigits: 0 })}</dd></div>
            <div><dt>Volumen FINRA · OFICIAL</dt><dd>{data.total_volume == null ? 'N/D' : formatNumber(data.total_volume, { maximumFractionDigits: 0 })}</dd></div>
          </dl>}
        </>}
      </>}
    </Panel>
  </main>;
}
