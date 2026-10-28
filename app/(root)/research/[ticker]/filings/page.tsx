import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatDate, formatMarketCapUsd, formatNumber } from '@/lib/format';
import { Badge } from '@/components/ui/badge';
import { PageHeader } from '@/components/ui/page-header';
import { Panel } from '@/components/ui/panel';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Documentos SEC',
  description: 'Formularios y cambios reportados por la empresa ante la SEC, con su fuente.',
};

type Side = { value: string; period: string; unit: string; source: { url: string | null; published_at: string | null } } | null;
type Figure = { metric: string; unit: string; outflow?: boolean; current: Side; previous: Side; label: string; change_pct: string | null; highlight: boolean };
type Excerpt = { text: string };
type Section = { section: string; label: string; status: string; reason?: string; change_count?: number; truncated?: boolean;
  changes: Array<{ kind: 'added' | 'removed' | 'modified'; before: Excerpt[]; after: Excerpt[] }> };
type Citation = { url: string | null; published_at: string | null; reported_period: string | null };
type Yoy = { status: string; reason?: string; form: string; page: number; total: number; current?: Citation; previous?: Citation;
  figures?: Figure[]; text?: { label: string; sections: Section[] } | null; text_reason?: string };

const KIND = { added: 'Añadido', removed: 'Eliminado', modified: 'Modificado' } as const;
const PER_PAGE_NOTE = 'Cada página es un informe distinto, del más reciente al más antiguo.';

function money(value: string, unit: string, metric: string, outflow = false): string {
  const n = outflow ? Math.abs(Number(value)) : Number(value);
  // Misma convencion en toda la tabla: dolares en estilo ingles compacto ($4.87B).
  if (metric === 'eps_diluted') return `${new Intl.NumberFormat('en-US', { style: 'currency', currency: /^[A-Z]{3}(\/|$)/.test(unit) ? unit.slice(0, 3) : 'USD' }).format(n)} por acción`;
  if (unit === 'USD') return formatMarketCapUsd(n);
  if (unit === 'shares') return `${new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 }).format(n)} acciones`;
  return formatNumber(n, { maximumFractionDigits: 2 }) + (unit ? ` ${unit}` : '');
}

function sourceLink(url: string | null) {
  return url && /^https:\/\//.test(url) ? <a className="text-teal-300 underline" href={url} rel="noopener noreferrer" target="_blank">SEC</a> : null;
}

export default async function FilingsYoyPage({ params, searchParams }: {
  params: Promise<{ ticker: string }>; searchParams: Promise<{ form?: string; page?: string }>;
}) {
  await requireAuthenticatedUser();
  const ticker = (await params).ticker.toUpperCase();
  const query = await searchParams;
  const form = query.form === '10-Q' ? '10-Q' : '10-K';
  const page = Math.min(200, Math.max(1, Number.parseInt(query.page ?? '1', 10) || 1));
  const data = await researchRequest<Yoy>(
    `/api/companies/${encodeURIComponent(ticker)}/filing-yoy?form=${form}&page=${page}`,
  ).catch(() => null);
  const href = (f: string, p: number) => `/research/${encodeURIComponent(ticker)}/filings?form=${f}&page=${p}`;
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
    <PageHeader title={`Informe frente al año anterior · ${ticker}`}
      back={<Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300" href={`/research/${encodeURIComponent(ticker)}`}>Volver a la empresa</Link>} />
    <nav aria-label="Tipo de informe" className="flex gap-3 text-sm">
      {(['10-K', '10-Q'] as const).map((f) => <Link key={f} aria-current={f === form ? 'page' : undefined}
        className={`inline-flex min-h-11 min-w-11 items-center justify-center ${f === form ? 'font-semibold text-teal-200' : 'text-gray-400 hover:text-teal-300'}`} href={href(f, 1)}>{f}</Link>)}
    </nav>
    {!data ? <p role="status" className="text-amber-300">No se pudo leer la comparación. No equivale a «sin cambios».</p>
      : data.status !== 'ready' || !data.current || !data.previous ? <p role="status" className="text-gray-400">{data.reason ?? 'Sin datos.'}</p>
      : <>
        <p className="text-sm text-gray-400">
          {form} del periodo {data.current.reported_period ? formatDate(data.current.reported_period) : 'N/D'} frente a {data.previous.reported_period ? formatDate(data.previous.reported_period) : 'N/D'}
          {' · '}{sourceLink(data.current.url)}{' · '}{sourceLink(data.previous.url)}
        </p>
        <Panel title="Cifras clave">
          {data.figures?.length ? <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead className="text-left text-xs text-gray-500"><tr><th className="py-1 pr-3">Métrica</th><th className="pr-3">Actual</th><th className="pr-3">Año anterior</th><th>Variación</th></tr></thead>
            <tbody>{data.figures.map((fig) => <tr className="border-t border-gray-800" key={`${fig.metric}-${fig.unit}`}>
              <td className="py-1.5 pr-3">{metricLabel(fig.metric)}{fig.outflow ? <span className="block text-xs text-gray-500">salida de caja, importe absoluto</span> : null}</td>
              <td className="pr-3">{fig.current ? <>{money(fig.current.value, fig.unit, fig.metric, fig.outflow)} {sourceLink(fig.current.source.url)}</> : 'N/D'}</td>
              <td className="pr-3">{fig.previous ? <>{money(fig.previous.value, fig.unit, fig.metric, fig.outflow)} {sourceLink(fig.previous.source.url)}</> : 'N/D'}</td>
              <td className={fig.highlight ? 'font-semibold text-amber-300' : 'text-gray-300'}>
                {fig.change_pct == null ? 'N/D' : `${Number(fig.change_pct) > 0 ? '+' : ''}${formatNumber(Number(fig.change_pct), { maximumFractionDigits: 1 })} %`}
                {' '}<span className="text-xs text-gray-500">{fig.change_pct == null ? 'N/D' : 'calculado'}</span>
              </td></tr>)}</tbody></table></div>
            : <p className="text-gray-400">Sin cifras guardadas para ambos periodos.</p>}
        </Panel>
        <Panel title="Cambios de texto">
          {data.text ? <>
            <p className="my-2 text-xs text-gray-500">{data.text.label}</p>
            <div className="space-y-4">{data.text.sections.map((section) => <section key={section.section}>
              <h3 className="font-medium text-gray-200">{section.label}</h3>
              {section.status !== 'changed' ? <p className="text-sm text-gray-400">{section.status === 'unchanged' ? 'Sin cambios en el texto identificado.' : section.reason ?? 'Sin datos de esta sección.'}</p>
                : <details className="mt-1" open={section.changes.length <= 3}><summary className="cursor-pointer text-sm text-gray-400">{section.change_count ?? section.changes.length} cambios{section.truncated ? ' (se muestran los primeros 20)' : ''}</summary>
                  <ul className="mt-2 space-y-3">{section.changes.map((change, i) => <li className="rounded border border-gray-800 p-3 text-sm" key={i}>
                    <Badge variant="outline">{KIND[change.kind]}</Badge>
                    {change.before.length ? <p className="mt-2 text-gray-500">Antes: «{change.before.map((e) => e.text).join(' ')}»</p> : null}
                    {change.after.length ? <p className="mt-1 text-gray-200">Ahora: «{change.after.map((e) => e.text).join(' ')}»</p> : null}
                  </li>)}</ul></details>}
            </section>)}</div></>
            : <p className="text-gray-400">{data.text_reason ?? 'Sin análisis de texto.'}</p>}
        </Panel>
        <nav aria-label="Páginas de informes" className="flex items-center gap-4 text-sm">
          {page > 1 && <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300" href={href(form, page - 1)}>Más reciente</Link>}
          <span>{page} / {data.total}</span>
          {page < data.total && <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300" href={href(form, page + 1)}>Anterior</Link>}
          <span className="sr-only">{PER_PAGE_NOTE}</span>
        </nav>
      </>}
  </main>;
}
