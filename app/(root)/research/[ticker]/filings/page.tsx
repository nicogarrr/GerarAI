import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatDate, type Formatters } from '@/lib/format';
import { getFormat, getLocale, getT } from '@/lib/i18n/server';
import type { TranslateFn } from '@/lib/i18n/translate';
import { Badge } from '@/components/ui/badge';
import { PageHeader } from '@/components/ui/page-header';
import { Panel } from '@/components/ui/panel';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('research.filingsYoy.metaTitle'), description: t('research.filingsYoy.metaDescription') };
}

type Side = { value: string; period: string; unit: string; source: { url: string | null; published_at: string | null } } | null;
type Figure = { metric: string; unit: string; outflow?: boolean; current: Side; previous: Side; label: string; change_pct: string | null; highlight: boolean };
type Excerpt = { text: string };
type Section = { section: string; label: string; status: string; reason?: string; change_count?: number; truncated?: boolean;
  changes: Array<{ kind: 'added' | 'removed' | 'modified'; before: Excerpt[]; after: Excerpt[] }> };
type Citation = { url: string | null; published_at: string | null; reported_period: string | null };
type Yoy = { status: string; reason?: string; form: string; page: number; total: number; current?: Citation; previous?: Citation;
  figures?: Figure[]; text?: { label: string; sections: Section[] } | null; text_reason?: string };

const KIND = { added: 'research.filingsYoy.kind.added', removed: 'research.filingsYoy.kind.removed', modified: 'research.filingsYoy.kind.modified' } as const;

function money(value: string, unit: string, metric: string, fmt: Formatters, t: TranslateFn, outflow = false): string {
  const n = outflow ? Math.abs(Number(value)) : Number(value);
  // Misma convencion en toda la tabla: el formato del idioma para todas las divisas (4,87 mil M US$).
  if (metric === 'eps_diluted') return t('research.filingsYoy.perShare', { amount: new Intl.NumberFormat(fmt.locale === 'en' ? 'en-US' : 'es-ES', { style: 'currency', currency: /^[A-Z]{3}(\/|$)/.test(unit) ? unit.slice(0, 3) : 'USD' }).format(n) });
  if (unit === 'USD') return fmt.formatMarketCapUsd(n);
  if (unit === 'shares') return t('research.filingsYoy.shares', { amount: fmt.formatCompact(n, { maximumFractionDigits: 2 }) });
  return fmt.formatNumber(n, { maximumFractionDigits: 2 }) + (unit ? ` ${unit}` : '');
}

function sourceLink(url: string | null) {
  return url && /^https:\/\//.test(url) ? <a className="text-teal-300 underline" href={url} rel="noopener noreferrer" target="_blank">SEC</a> : null;
}

export default async function FilingsYoyPage({ params, searchParams }: {
  params: Promise<{ ticker: string }>; searchParams: Promise<{ form?: string; page?: string }>;
}) {
  await requireAuthenticatedUser();
  const t = await getT();
  const fmt = await getFormat();
  const locale = await getLocale();
  const ticker = (await params).ticker.toUpperCase();
  const query = await searchParams;
  const form = query.form === '10-Q' ? '10-Q' : '10-K';
  const page = Math.min(200, Math.max(1, Number.parseInt(query.page ?? '1', 10) || 1));
  const data = await researchRequest<Yoy>(
    `/api/companies/${encodeURIComponent(ticker)}/filing-yoy?form=${form}&page=${page}`,
  ).catch(() => null);
  const href = (f: string, p: number) => `/research/${encodeURIComponent(ticker)}/filings?form=${f}&page=${p}`;
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
    <PageHeader title={t('research.filingsYoy.title', { ticker })}
      back={<Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300" href={`/research/${encodeURIComponent(ticker)}`}>{t('research.filingsYoy.back')}</Link>} />
    <nav aria-label={t('research.filingsYoy.reportTypeAria')} className="flex gap-3 text-sm">
      {(['10-K', '10-Q'] as const).map((f) => <Link key={f} aria-current={f === form ? 'page' : undefined}
        className={`inline-flex min-h-11 min-w-11 items-center justify-center ${f === form ? 'font-semibold text-teal-200' : 'text-gray-400 hover:text-teal-300'}`} href={href(f, 1)}>{f}</Link>)}
    </nav>
    {!data ? <p role="status" className="text-amber-300">{t('research.filingsYoy.loadError')}</p>
      : data.status !== 'ready' || !data.current || !data.previous ? <p role="status" className="text-gray-400">{data.reason ?? t('research.filingsYoy.noData')}</p>
      : <>
        <p className="text-sm text-gray-400">
          {t('research.filingsYoy.periodLine', { form, current: data.current.reported_period ? formatDate(data.current.reported_period, undefined, undefined, locale) : fmt.na, previous: data.previous.reported_period ? formatDate(data.previous.reported_period, undefined, undefined, locale) : fmt.na })}
          {' · '}{sourceLink(data.current.url)}{' · '}{sourceLink(data.previous.url)}
        </p>
        <Panel title={t('research.filingsYoy.keyFigures')}>
          {data.figures?.length ? <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead className="text-left text-xs text-gray-500"><tr><th className="py-1 pr-3">{t('research.filingsYoy.colMetric')}</th><th className="pr-3">{t('research.filingsYoy.colCurrent')}</th><th className="pr-3">{t('research.filingsYoy.colPrevious')}</th><th>{t('research.filingsYoy.colChange')}</th></tr></thead>
            <tbody>{data.figures.map((fig) => <tr className="border-t border-gray-800" key={`${fig.metric}-${fig.unit}`}>
              <td className="py-1.5 pr-3">{metricLabel(fig.metric, locale)}{fig.outflow ? <span className="block text-xs text-gray-500">{t('research.filingsYoy.outflowNote')}</span> : null}</td>
              <td className="pr-3">{fig.current ? <>{money(fig.current.value, fig.unit, fig.metric, fmt, t, fig.outflow)} {sourceLink(fig.current.source.url)}</> : 'N/D'}</td>
              <td className="pr-3">{fig.previous ? <>{money(fig.previous.value, fig.unit, fig.metric, fmt, t, fig.outflow)} {sourceLink(fig.previous.source.url)}</> : 'N/D'}</td>
              <td className={fig.highlight ? 'font-semibold text-amber-300' : 'text-gray-300'}>
                {fig.change_pct == null ? fmt.na : `${Number(fig.change_pct) > 0 ? '+' : ''}${fmt.formatNumber(Number(fig.change_pct), { maximumFractionDigits: 1 })}${locale === 'en' ? '%' : ' %'}`}
                {' '}<span className="text-xs text-gray-500">{fig.change_pct == null ? fmt.na : t('research.filingsYoy.calculated')}</span>
              </td></tr>)}</tbody></table></div>
            : <p className="text-gray-400">{t('research.filingsYoy.noFigures')}</p>}
        </Panel>
        <Panel title={t('research.filingsYoy.textChanges')}>
          {data.text ? <>
            <p className="my-2 text-xs text-gray-500">{data.text.label}</p>
            <div className="space-y-4">{data.text.sections.map((section) => <section key={section.section}>
              <h3 className="font-medium text-gray-200">{section.label}</h3>
              {section.status !== 'changed' ? <p className="text-sm text-gray-400">{section.status === 'unchanged' ? t('research.filingsYoy.unchangedText') : section.reason ?? t('research.filingsYoy.noSectionData')}</p>
                : <details className="mt-1" open={section.changes.length <= 3}><summary className="cursor-pointer text-sm text-gray-400">{t('research.filingsYoy.changesCount', { count: section.change_count ?? section.changes.length })}{section.truncated ? t('research.filingsYoy.truncated') : ''}</summary>
                  <ul className="mt-2 space-y-3">{section.changes.map((change, i) => <li className="rounded border border-gray-800 p-3 text-sm" key={i}>
                    <Badge variant="outline">{t(KIND[change.kind])}</Badge>
                    {change.before.length ? <p className="mt-2 text-gray-500">{t('research.filingsYoy.before', { text: change.before.map((e) => e.text).join(' ') })}</p> : null}
                    {change.after.length ? <p className="mt-1 text-gray-200">{t('research.filingsYoy.after', { text: change.after.map((e) => e.text).join(' ') })}</p> : null}
                  </li>)}</ul></details>}
            </section>)}</div></>
            : <p className="text-gray-400">{data.text_reason ?? t('research.filingsYoy.noTextAnalysis')}</p>}
        </Panel>
        <nav aria-label={t('research.filingsYoy.pagesAria')} className="flex items-center gap-4 text-sm">
          {page > 1 && <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300" href={href(form, page - 1)}>{t('research.filingsYoy.newer')}</Link>}
          <span>{page} / {data.total}</span>
          {page < data.total && <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300" href={href(form, page + 1)}>{t('research.filingsYoy.older')}</Link>}
          <span className="sr-only">{t('research.filingsYoy.perPageNote')}</span>
        </nav>
      </>}
  </main>;
}
