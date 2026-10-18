import Link from 'next/link';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getDataHealth, type DataSourceHealth } from '@/lib/actions/data-health.actions';
import { formatNumber, formatUserDateTime } from '@/lib/format';
import { PageHeader } from '@/components/ui/page-header';
import { Panel } from '@/components/ui/panel';
import { sourceDisplay } from '@/lib/research/source-display';

export const dynamic = 'force-dynamic';
const labels: Record<string, string> = { available: 'Con registros', stale: 'Datos antiguos', empty: 'Sin datos', error: 'Error de lectura', degraded: 'Consulta fallida', observed: 'Consulta registrada' };
const stamp = (value: string | null) => value ? formatUserDateTime(value) : 'N/D';
const PAGE_SIZE = 12;

function SourceCard({ row }: { row: DataSourceHealth }) {
  return <article className="min-w-0 rounded-lg border border-gray-800 p-4">
    <h2 className="break-words font-semibold">{row.layer} · {row.source ? sourceDisplay(row.source) : 'Sin fuente'}</h2>
    <p className={['error', 'stale'].includes(row.status) ? 'text-amber-300' : 'text-gray-400'}>{labels[row.status] ?? 'N/D'}</p>
    <p className="mt-3 text-2xl">{row.coverage_pct === null ? 'N/D' : `${formatNumber(row.coverage_pct, { maximumFractionDigits: 1 })} %`}</p>
    <p className="text-xs text-gray-400">{row.covered === null ? 'N/D' : formatNumber(row.covered, { maximumFractionDigits: 0 })} de {formatNumber(row.total, { maximumFractionDigits: 0 })} empresas con registros</p>
    <p className="mt-2 text-sm">Última escritura: {stamp(row.last_update)}</p>
    {row.max_age_days !== null && <p className="text-xs text-gray-500">Límite de antigüedad: {row.max_age_days} días</p>}
    {row.reason && <p className="mt-2 text-sm text-amber-300">{row.reason}</p>}
  </article>;
}

export default async function DataHealthPage({ searchParams }: { searchParams: Promise<{ page?: string; connectors?: string }> }) {
  await requireAuthenticatedUser();
  const query = await searchParams;
  const data = await getDataHealth().catch(() => null);
  const sources = data?.sources.filter((row) => row.layer !== 'Noticias') ?? [];
  const newsSources = data?.sources.filter((row) => row.layer === 'Noticias') ?? [];
  const totalPages = Math.max(1, Math.ceil(newsSources.length / PAGE_SIZE));
  const connectorPages = Math.max(1, Math.ceil((data?.connectors.length ?? 0) / PAGE_SIZE));
  const connectorPage = Math.min(connectorPages, Math.max(1, Number.parseInt(query.connectors ?? '1', 10) || 1));
  const page = Math.min(totalPages, Math.max(1, Number.parseInt(query.page ?? '1', 10) || 1));
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
    <PageHeader title="Salud de los datos" back={<Link href="/research" className="text-teal-300">Research</Link>} />
    {!data ? <Panel title="Error de lectura"><p>No se pudo leer el inventario.</p><Link className="text-teal-300" href="/research/data-health">Reintentar</Link></Panel> : <>
      <Panel title="Cobertura por fuente">
        <p className="mb-2 text-sm text-gray-400">Empresas con algún registro de la fuente sobre el total de empresas. No mide la completitud de los datos.</p>
        <p className="mb-4 text-sm text-gray-400">Las fechas indican escrituras en la base de datos, no disponibilidad del proveedor. Corte: {stamp(data.as_of)}.</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sources.map((row, index) => <SourceCard key={`${row.layer}-${row.source}-${index}`} row={row} />)}
        </div>
        {newsSources.length > 0 && <details className="mt-4" open={page > 1}>
          <summary className="cursor-pointer text-teal-300">Fuentes de noticias ({formatNumber(newsSources.length, { maximumFractionDigits: 0 })})</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{newsSources.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((row, index) => <SourceCard key={`${row.source}-${index}`} row={row} />)}</div>
          {totalPages > 1 && <nav aria-label="Páginas de fuentes de noticias" className="mt-4 flex items-center gap-4">
            {page > 1 && <Link href={`?page=${page - 1}&connectors=${connectorPage}`} className="text-teal-300">Anterior</Link>}
            <span>{page} / {totalPages}</span>
            {page < totalPages && <Link href={`?page=${page + 1}&connectors=${connectorPage}`} className="text-teal-300">Siguiente</Link>}
          </nav>}
        </details>}
      </Panel>
      <Panel title="Consultas registradas">
        <p className="mb-3 text-sm text-gray-400">No todos los proveedores registran sus consultas.</p>
        {!data.connectors.length ? <p>Sin registro de consultas.</p> : <details open={connectorPage > 1}><summary className="cursor-pointer text-teal-300">Ver {formatNumber(data.connectors.length, { maximumFractionDigits: 0 })} registros</summary><ul className="mt-3 grid gap-2 sm:grid-cols-2">{data.connectors.slice((connectorPage - 1) * PAGE_SIZE, connectorPage * PAGE_SIZE).map((row, i) => <li className="min-w-0 break-words rounded border border-gray-800 p-3 text-sm" key={`${row.source}-${i}`}>{sourceDisplay(row.source)} · {labels[row.status] ?? 'N/D'}<br />Último éxito: {stamp(row.last_success)}<br />Último intento: {stamp(row.last_attempt)}{row.errors !== null && row.errors > 0 && <p className="text-amber-300">{row.errors} fallos consecutivos</p>}</li>)}</ul><nav aria-label="Páginas de consultas" className="mt-4 flex gap-4">{connectorPage > 1 && <Link className="text-teal-300" href={`?page=${page}&connectors=${connectorPage - 1}`}>Anterior</Link>}<span>{connectorPage} / {connectorPages}</span>{connectorPage < connectorPages && <Link className="text-teal-300" href={`?page=${page}&connectors=${connectorPage + 1}`}>Siguiente</Link>}</nav></details>}
      </Panel>
    </>}
  </main>;
}
