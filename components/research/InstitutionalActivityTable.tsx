import { formatPercent } from '@/lib/format';
import { DEFAULT_LOCALE, intlLocale, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import type { ActivityFilter, InstitutionalActivity } from '@/lib/research/institutional-holders';

const FILTERS: ActivityFilter[] = ['all', 'aumenta', 'reduce', 'nuevo', 'vende_todo'];

export function InstitutionalActivityTable({ data, locale = DEFAULT_LOCALE, baseHref }: {
  data: InstitutionalActivity | null; locale?: Locale; baseHref: string;
}) {
  const t = createTranslator(locale);
  const intl = intlLocale(locale);
  const labels = {
    title: t('research.institutionalActivity.title'),
    all: t('research.institutionalActivity.all'),
    aumenta: t('research.institutionalActivity.aumenta'),
    reduce: t('research.institutionalActivity.reduce'),
    nuevo: t('research.institutionalActivity.nuevo'),
    vende_todo: t('research.institutionalActivity.vende_todo'),
    manager: t('research.institutionalActivity.manager'),
    status: t('research.institutionalActivity.status'),
    current: t('research.institutionalActivity.current'),
    previous: t('research.institutionalActivity.previous'),
    change: t('research.institutionalActivity.change'),
    value: t('research.institutionalActivity.value'),
    capital: t('research.institutionalActivity.capital'),
    filed: t('research.institutionalActivity.filed'),
    na: t('research.institutionalActivity.na'),
    legacy: t('research.institutionalActivity.legacy'),
    unlinked: t('research.institutionalActivity.unlinked'),
    missing: t('research.institutionalActivity.missing'),
    identity: t('research.institutionalActivity.identity'),
    error: t('research.institutionalActivity.error'),
    empty: t('research.institutionalActivity.empty'),
    basis: t('research.institutionalActivity.basis'),
    prevPage: t('research.institutionalActivity.prevPage'),
    nextPage: t('research.institutionalActivity.nextPage'),
    filters: t('research.institutionalActivity.filters'),
  };
  const na = t('research.institutionalActivity.na');
  const fmt = (v: number | null) => v === null ? na : new Intl.NumberFormat(intl, { maximumFractionDigits: 0 }).format(v);
  const href = (filter: ActivityFilter, page: number) => {
    const [path, search = ''] = baseHref.split('?');
    const query = new URLSearchParams(search.split('#')[0]);
    query.set('ia_status', filter); query.set('ia_page', String(page));
    return `${path}?${query}#superinversores`;
  };
  const message = !data ? 'error' : data.status === 'sin_snapshot_vinculado' ? 'unlinked'
    : data.status === 'sin_identificador' ? 'identity' : data.status === 'sin_detalle' ? 'legacy' : 'missing';
  return (
    <section aria-label={t('research.institutionalActivity.title')} className="min-w-0 space-y-4 rounded-lg border border-gray-800 p-4" data-testid="institutional-activity">
      <h3 className="text-base font-semibold text-gray-100">{t('research.institutionalActivity.title')}</h3>
      {!data || data.status !== 'ok' ? <p className="text-sm text-gray-400" role="status">{labels[message]}</p> : <>
        <p className="text-sm text-gray-400">{t('research.institutionalActivity.periods', { current: data.period ?? na, previous: data.prior_period ?? na })}</p>
        <nav aria-label={t('research.institutionalActivity.filters')} className="flex flex-wrap gap-2">
          {FILTERS.map(filter => <a aria-current={data.filter === filter ? 'page' : undefined} className="rounded border border-gray-700 px-3 py-2 text-sm text-teal-300 aria-[current=page]:bg-gray-800" href={href(filter, 1)} key={filter}>{labels[filter]}</a>)}
        </nav>
        {data.rows.length ? <div className="max-h-[32rem] overflow-auto" tabIndex={0} role="region" aria-label={t('research.institutionalActivity.title')}>
          <table className="w-full text-left text-sm tabular-nums">
            <caption className="sr-only">{t('research.institutionalActivity.title')}</caption>
            <thead className="sticky top-0 bg-gray-950"><tr>{(['manager', 'status', 'current', 'previous', 'change', 'value', 'capital', 'filed'] as const).map(key => <th scope="col" className="whitespace-nowrap p-2 text-gray-400" key={key}>{labels[key]}</th>)}</tr></thead>
            <tbody>{data.rows.map(row => <tr className="border-t border-gray-800" key={row.cik}>
              <th scope="row" className="min-w-48 p-2 font-medium text-gray-100">{row.filing_url || row.prev_filing_url ? <a className="text-teal-300 underline" href={(row.filing_url || row.prev_filing_url) as string} target="_blank" rel="noopener noreferrer">{row.name || row.cik}</a> : row.name || row.cik}</th>
              <td className="p-2 text-gray-300">{row.status && FILTERS.includes(row.status as ActivityFilter) ? labels[row.status as ActivityFilter] : row.status === 'igual' ? t('research.institucionales.status.igual') : row.status === 'sin_13f_aun' ? t('research.institucionales.status.sin13fAun') : row.status === 'sin_13f_previo' ? t('research.institucionales.status.sin13fPrevio') : na}</td>
              <td className="p-2">{fmt(row.shares)}</td><td className="p-2">{fmt(row.prev_shares)}</td><td className="p-2">{fmt(row.change)}</td><td className="p-2">{fmt(row.reported_value_usd)}</td><td className="p-2">{row.company_ownership_pct === null ? na : formatPercent(row.company_ownership_pct, { fromRatio: false }, na, locale)}</td><td className="whitespace-nowrap p-2">{row.filed ?? na}</td>
            </tr>)}</tbody>
          </table>
        </div> : <p role="status" className="text-sm text-gray-400">{t('research.institutionalActivity.empty')}</p>}
        <nav aria-label={t('research.institutionalActivity.pages', { page: data.page, pages: Math.max(data.pages ?? 0, 1), total: data.total ?? 0 })} className="flex flex-wrap items-center gap-4 text-sm">
          {data.page > 1 ? <a className="text-teal-300" href={href(data.filter, data.page - 1)}>{t('research.institutionalActivity.prevPage')}</a> : null}
          <span>{t('research.institutionalActivity.pages', { page: data.page, pages: Math.max(data.pages ?? 0, 1), total: data.total ?? 0 })}</span>
          {data.page < (data.pages ?? 0) ? <a className="text-teal-300" href={href(data.filter, data.page + 1)}>{t('research.institutionalActivity.nextPage')}</a> : null}
        </nav>
        <p className="text-xs text-gray-400">{t('research.institutionalActivity.basis')}</p>
        <p className="text-xs text-gray-400">{t('research.institutionalActivity.fetched', { date: data.fetched_at ?? na })}{data.source_url ? <> · <a className="text-teal-300 underline" href={data.source_url} target="_blank" rel="noopener noreferrer">SEC</a></> : null}</p>
      </>}
    </section>
  );
}
