import { DEFAULT_LOCALE, intlLocale, type Locale } from '@/lib/i18n/locale';
import type { TranslationKey } from '@/lib/i18n/t';
import { createTranslator } from '@/lib/i18n/translate';
import { compactShares, pct, type InstitutionalHolder, type InstitutionalHolders, type InstitutionalStatus } from '@/lib/research/institutional-holders';

const STATUS_KEYS = {
  nuevo: 'research.institucionales.status.nuevo',
  aumenta: 'research.institucionales.status.aumenta',
  reduce: 'research.institucionales.status.reduce',
  igual: 'research.institucionales.status.igual',
  vende_todo: 'research.institucionales.status.vendeTodo',
  sin_13f_aun: 'research.institucionales.status.sin13fAun',
  sin_13f_previo: 'research.institucionales.status.sin13fPrevio',
} as const satisfies Record<InstitutionalStatus, TranslationKey>;

const UP = 'border-emerald-800 text-emerald-300';
const DOWN = 'border-red-900 text-red-300';
const FLAT = 'border-gray-700 text-gray-400';
const TONE: Record<InstitutionalStatus, string> = {
  nuevo: UP, aumenta: UP, reduce: DOWN, vende_todo: DOWN, igual: FLAT, sin_13f_aun: FLAT, sin_13f_previo: FLAT,
};

function fmtDate(value: string | null | undefined, intl: string): string {
  if (!value) return '—';
  const [y, m, d] = value.split('-').map(Number);
  return new Intl.DateTimeFormat(intl, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m - 1, d));
}

function Row({ holder, intl, t, mode }: { holder: InstitutionalHolder; intl: string; t: ReturnType<typeof createTranslator>; mode: 'top' | 'move' }) {
  const status = holder.status || null;
  const change = pct(holder.change_pct, intl, true);
  return (
    <li className="flex flex-col gap-1 border-b border-gray-800/70 py-2 last:border-0">
      <div className="flex items-baseline justify-between gap-3">
        {holder.filing_url ?? holder.prev_filing_url ? (
          <a className="min-w-0 truncate text-sm font-medium text-teal-300 hover:text-teal-200" href={(holder.filing_url ?? holder.prev_filing_url) as string} rel="noopener noreferrer" target="_blank">{holder.name}</a>
        ) : (
          <span className="min-w-0 truncate text-sm font-medium text-gray-100">{holder.name}</span>
        )}
        <span className="shrink-0 text-sm tabular-nums text-gray-100">
          {mode === 'top' ? compactShares(holder.shares, intl) : compactShares(holder.change, intl, true)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
        {status ? <span className={`rounded-full border px-2 py-0.5 ${TONE[status]}`}>{t(STATUS_KEYS[status])}</span> : null}
        {mode === 'top' && holder.pct_of_13f !== null ? <span>{t('research.institucionales.pctOf13f', { pct: pct(holder.pct_of_13f, intl) ?? '—' })}</span> : null}
        {mode === 'top' ? (
          <span>{change ? t('research.institucionales.vsPrior', { change }) : t('research.institucionales.prevShares', { shares: compactShares(holder.prev_shares, intl) })}</span>
        ) : (
          <span>{t('research.institucionales.fromTo', { from: compactShares(holder.prev_shares, intl), to: compactShares(holder.shares, intl) })}</span>
        )}
      </div>
    </li>
  );
}

/**
 * Todos los gestores 13F de la acción (no solo los superinversores revisados):
 * mayores tenedores, quién compra y quién vende frente al trimestre anterior.
 * Cada nombre enlaza a su 13F en EDGAR; el pie cita el fichero de la SEC.
 */
export function InstitutionalHoldersPanel({ data, locale = DEFAULT_LOCALE }: { data: InstitutionalHolders | null; locale?: Locale }) {
  const t = createTranslator(locale);
  const intl = intlLocale(locale);
  const title = <h3 className="text-base font-semibold text-gray-100">{t('research.institucionales.title')}</h3>;
  if (!data || data.status !== 'ok' || !data.totals) {
    const message = !data
      ? t('research.institucionales.loadError')
      : data.status === 'sin_identificador'
        ? (data.identity_source ?? t('research.institucionales.noCusip'))
        : t('research.institucionales.empty');
    return (
      <section aria-label={t('research.institucionales.title')} className="space-y-2 rounded-lg border border-gray-800 p-4" data-testid="institucionales">
        {title}
        <p className="text-sm text-gray-400" role="status">{message}</p>
      </section>
    );
  }
  const totals = data.totals;
  const counts: [InstitutionalStatus, number][] = [
    ['nuevo', totals.nuevo], ['aumenta', totals.aumenta], ['reduce', totals.reduce], ['vende_todo', totals.vende_todo], ['sin_13f_aun', totals.sin_13f_aun], ['sin_13f_previo', totals.sin_13f_previo],
  ];
  return (
    <section aria-label={t('research.institucionales.title')} className="space-y-4 rounded-lg border border-gray-800 p-4" data-testid="institucionales">
      <header className="space-y-1">
        {title}
        <p className="text-sm text-gray-300">
          {t('research.institucionales.summary', {
            holders: new Intl.NumberFormat(intl).format(totals.holders),
            prior: new Intl.NumberFormat(intl).format(totals.holders_prior),
            shares: compactShares(totals.shares, intl),
            period: fmtDate(data.period, intl),
          })}
        </p>
        <p className="text-xs text-gray-500">
          {t('research.institucionales.net', { net: compactShares(totals.net_comparable, intl, true), prior: fmtDate(data.prior_period, intl) })}
        </p>
        <ul aria-label={t('research.institucionales.countsLabel')} className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-xs text-gray-400">
          {counts.map(([status, n]) => <li key={status}>{t(STATUS_KEYS[status])}: <span className="tabular-nums text-gray-200">{n}</span></li>)}
        </ul>
      </header>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="min-w-0">
          <h4 className="text-sm font-medium text-gray-300">{t('research.institucionales.top')}</h4>
          <ol className="mt-1">{data.top_holders.map((h) => <Row holder={h} intl={intl} key={h.cik} mode="top" t={t} />)}</ol>
        </div>
        <div className="min-w-0">
          <h4 className="text-sm font-medium text-gray-300">{t('research.institucionales.buyers')}</h4>
          {data.buyers.length ? <ol className="mt-1">{data.buyers.map((h) => <Row holder={h} intl={intl} key={h.cik} mode="move" t={t} />)}</ol> : <p className="mt-1 text-sm text-gray-500">{t('research.institucionales.none')}</p>}
        </div>
        <div className="min-w-0">
          <h4 className="text-sm font-medium text-gray-300">{t('research.institucionales.sellers')}</h4>
          {data.sellers.length ? <ol className="mt-1">{data.sellers.map((h) => <Row holder={h} intl={intl} key={h.cik} mode="move" t={t} />)}</ol> : <p className="mt-1 text-sm text-gray-500">{t('research.institucionales.none')}</p>}
        </div>
      </div>
      <p className="text-xs text-gray-500">
        {t('research.institucionales.source', { period: fmtDate(data.period, intl), prior: fmtDate(data.prior_period, intl) })}{' '}
        {data.source ? <a className="text-teal-300 underline decoration-gray-700 underline-offset-4" href={data.source.dataset_url} rel="noopener noreferrer" target="_blank">{t('research.institucionales.sourceLink')}</a> : null}
        {' · '}{t('research.institucionales.limits')}
      </p>
    </section>
  );
}
