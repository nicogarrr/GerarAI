import { DEFAULT_LOCALE, intlLocale, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { datasetLabel, type FundHolder, type FundHolders } from '@/lib/research/fund-holders';
import { compactShares, pct } from '@/lib/research/institutional-holders';

function fmtDate(value: string | null | undefined, intl: string): string {
  if (!value) return '—';
  const [y, m, d] = value.split('-').map(Number);
  return new Intl.DateTimeFormat(intl, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m - 1, d));
}

function usd(value: number | null, intl: string): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(intl, { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function Row({ fund, intl, t, mode }: { fund: FundHolder; intl: string; t: ReturnType<typeof createTranslator>; mode: 'shares' | 'weight' }) {
  const weight = pct(fund.weight_pct, intl);
  return (
    <li className="flex flex-col gap-1 border-b border-gray-800/70 py-2 last:border-0">
      <div className="flex items-baseline justify-between gap-3">
        {fund.filing_url ? (
          <a className="min-w-0 truncate text-sm font-medium text-teal-300 hover:text-teal-200" href={fund.filing_url} rel="noopener noreferrer" target="_blank">{fund.name}</a>
        ) : (
          <span className="min-w-0 truncate text-sm font-medium text-gray-100">{fund.name}</span>
        )}
        <span className="shrink-0 text-sm tabular-nums text-gray-100">
          {mode === 'shares' ? compactShares(fund.shares ?? 0, intl) : (weight ?? '—')}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
        {mode === 'shares' ? (
          <span>{t('research.fondos.weightOfFund', { pct: weight ?? '—' })}</span>
        ) : (
          <span>{t('research.fondos.sharesValue', { shares: compactShares(fund.shares ?? 0, intl), value: usd(fund.value_usd, intl) })}</span>
        )}
        <span>{t('research.fondos.portfolioAt', { date: fmtDate(fund.report_date, intl) })}</span>
        {fund.net_assets_usd !== null ? <span>{t('research.fondos.netAssets', { value: usd(fund.net_assets_usd, intl) })}</span> : null}
      </div>
    </li>
  );
}

/**
 * Fondos y ETF de EE. UU. que tienen la acción (SEC Form N-PORT): los de más
 * acciones (volumen pasivo) y aquellos donde más pesa (apuestas temáticas).
 * Cada nombre enlaza a su N-PORT en EDGAR; el pie cita el fichero de la SEC.
 */
export function FundHoldersPanel({ data, locale = DEFAULT_LOCALE }: { data: FundHolders | null; locale?: Locale }) {
  const t = createTranslator(locale);
  const intl = intlLocale(locale);
  const title = <h3 className="text-base font-semibold text-gray-100">{t('research.fondos.title')}</h3>;
  if (!data || data.status !== 'ok' || !data.totals) {
    const message = !data
      ? t('research.fondos.loadError')
      : data.status === 'sin_identificador'
        ? (data.identity_source ?? t('research.fondos.noCusip'))
        : t('research.fondos.empty');
    return (
      <section aria-label={t('research.fondos.title')} className="space-y-2 rounded-lg border border-gray-800 p-4" data-testid="fondos">
        {title}
        <p className="text-sm text-gray-400" role="status">{message}</p>
      </section>
    );
  }
  return (
    <section aria-label={t('research.fondos.title')} className="space-y-4 rounded-lg border border-gray-800 p-4" data-testid="fondos">
      <header className="space-y-1">
        {title}
        <p className="text-sm text-gray-300">
          {t('research.fondos.summary', {
            funds: new Intl.NumberFormat(intl).format(data.totals.funds),
            shares: compactShares(data.totals.shares, intl),
            value: usd(data.totals.value_usd, intl),
            dataset: datasetLabel(data.dataset, intl),
          })}
        </p>
      </header>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <h4 className="text-sm font-medium text-gray-300">{t('research.fondos.top')}</h4>
          <ol className="mt-1">{data.top_funds.map((f) => <Row fund={f} intl={intl} key={`s-${f.accession}`} mode="shares" t={t} />)}</ol>
        </div>
        <div className="min-w-0">
          <h4 className="text-sm font-medium text-gray-300">{t('research.fondos.byWeight')}</h4>
          <ol className="mt-1">{data.by_weight.map((f) => <Row fund={f} intl={intl} key={`w-${f.accession}`} mode="weight" t={t} />)}</ol>
        </div>
      </div>
      <p className="text-xs text-gray-500">
        {t('research.fondos.source')}{' '}
        {data.source ? (
          <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={data.source.page} rel="noopener noreferrer" target="_blank">SEC Form N-PORT Data Sets</a>
        ) : 'SEC Form N-PORT Data Sets'}
        {' · '}{t('research.fondos.limits')}
      </p>
    </section>
  );
}
