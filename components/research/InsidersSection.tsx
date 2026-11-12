import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { DEFAULT_LOCALE, intlLocale, type Locale } from '@/lib/i18n/locale';
import type { TranslationKey } from '@/lib/i18n/t';
import { createTranslator } from '@/lib/i18n/translate';
import { compactUsd, type InsiderNature, type InsiderRow, type InsiderSummary, type InsiderWindow } from '@/lib/research/insiders-politicians';

const MAX_ROWS = 15;

const NATURE_KEYS = {
  compra_mercado: 'research.insidersV2.nature.compraMercado',
  venta_mercado: 'research.insidersV2.nature.ventaMercado',
  ejercicio: 'research.insidersV2.nature.ejercicio',
  concesion: 'research.insidersV2.nature.concesion',
  retencion_fiscal: 'research.insidersV2.nature.retencionFiscal',
  regalo: 'research.insidersV2.nature.regalo',
  otra: 'research.insidersV2.nature.otra',
} as const satisfies Record<InsiderNature, TranslationKey>;

function fmtDate(value: string | null, locale: Locale): string {
  if (!value) return '—';
  const [y, m, d] = value.split('-').map(Number);
  return new Intl.DateTimeFormat(intlLocale(locale), { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m - 1, d));
}

function fmtNumber(value: number, locale: Locale, digits = 0): string {
  return new Intl.NumberFormat(intlLocale(locale), { maximumFractionDigits: digits }).format(value);
}

function sideCell(side: InsiderWindow['buys'], locale: Locale, t: ReturnType<typeof createTranslator>): string {
  if (!side.trades) return '—';
  return t('research.insidersV2.tradesValue', { trades: side.trades, value: compactUsd(side.value, locale) });
}

const NATURE_TONE: Record<string, string> = {
  compra_mercado: 'border-teal-800 text-teal-300',
  venta_mercado: 'border-red-900 text-red-300',
};

function RowCard({ row, locale }: { row: InsiderRow; locale: Locale }) {
  const t = createTranslator(locale);
  return (
    <li className="rounded-lg border border-gray-800 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-gray-100">{row.insider ?? '—'}</span>
        <Badge className={NATURE_TONE[row.nature] ?? 'border-gray-700 text-gray-300'} variant="outline">{t(NATURE_KEYS[row.nature] ?? NATURE_KEYS.otra)}</Badge>
        {row.rule_10b5_1 ? <Badge className="border-amber-900 text-amber-300" variant="outline">{t('research.insidersV2.plan')}</Badge> : null}
        {row.is_derivative ? <Badge className="border-gray-700 text-gray-400" variant="outline">{t('research.insidersV2.derivative')}</Badge> : null}
        {row.ownership === 'I' ? <Badge className="border-gray-700 text-gray-400" variant="outline">{t('research.insidersV2.indirect')}</Badge> : null}
      </div>
      {row.role ? <p className="mt-1 text-xs text-gray-500">{row.role}</p> : null}
      <p className="mt-1 text-sm text-gray-300">
        {fmtDate(row.tx_date, locale)} · {row.shares !== null && row.price
          ? t('research.insidersV2.row', { shares: fmtNumber(row.shares, locale), price: `${fmtNumber(row.price, locale, 2)} $` })
          : row.shares !== null ? fmtNumber(row.shares, locale) : '—'}
        {row.value ? ` = ${compactUsd(row.value, locale)}` : ''}
      </p>
      {row.pct_of_holdings !== null ? <p className="text-xs text-teal-300">{t('research.insidersV2.pctHoldings', { pct: fmtNumber(row.pct_of_holdings, locale, 1) })}</p> : null}
      <p className={`mt-1 text-xs ${row.late ? 'text-amber-300' : 'text-gray-500'}`}>
        {row.late
          ? t('research.insidersV2.filedLate', { date: fmtDate(row.filing_date, locale), days: row.days_late ?? 0 })
          : t('research.insidersV2.filedOnTime', { date: fmtDate(row.filing_date, locale) })}
        {row.source_url ? <>{' · '}<a className="text-teal-300 underline underline-offset-2" href={row.source_url} rel="noreferrer" target="_blank">{t('research.insidersV2.filing', { form: `Form ${row.form}` })}</a></> : null}
      </p>
    </li>
  );
}

/**
 * Insiders del ticker (Form 4/5, SEC): compra neta en mercado a 3/6/12 meses
 * sin ejercicios, concesiones, retenciones ni regalos; compras en grupo;
 * primeras compras en años; retraso de cada Form 4; cada fila con su filing.
 * Todas las cifras vienen del backend (deterministas).
 */
export function InsidersSection({ ticker, summary, locale = DEFAULT_LOCALE }: { ticker: string; summary: InsiderSummary | null; locale?: Locale }) {
  const t = createTranslator(locale);
  if (summary === null) return <p className="text-sm text-gray-400" role="status">{t('research.insidersV2.loadError')}</p>;
  if (summary.status !== 'ok') return <p className="text-sm text-gray-400" role="status">{t('research.insidersV2.empty', { ticker })}</p>;
  const year = summary.windows.find((w) => w.days === 365);
  const excluded = Object.entries(year?.excluded ?? {}).filter(([, n]) => (n ?? 0) > 0);
  // Primero lo que importa: compras y ventas en mercado. Si no hay, todo.
  const market = summary.transactions.filter((row) => row.nature === 'compra_mercado' || row.nature === 'venta_mercado');
  const rows = (market.length ? market : summary.transactions).slice(0, MAX_ROWS);
  return (
    <div className="grid gap-4" data-testid="insiders-section">
      <section>
        <h3 className="mb-2 text-sm font-semibold text-gray-200">{t('research.insidersV2.netTitle')}</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[320px] text-left text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th className="py-1 pr-2 font-normal">{t('research.insidersV2.colWindow')}</th>
                <th className="py-1 pr-2 font-normal">{t('research.insidersV2.buys')}</th>
                <th className="py-1 pr-2 font-normal">{t('research.insidersV2.sells')}</th>
                <th className="py-1 font-normal">{t('research.insidersV2.net')}</th>
              </tr>
            </thead>
            <tbody>
              {summary.windows.map((w) => (
                <tr className="border-t border-gray-800 align-top" key={w.days}>
                  <td className="py-1.5 pr-2 text-gray-300">
                    {t('research.insidersV2.months', { n: Math.round(w.days / 30) })}
                    {!w.covered && summary.coverage?.first_filing ? <span className="block text-xs text-gray-500">{t('research.insidersV2.notCovered', { date: fmtDate(summary.coverage.first_filing, locale) })}</span> : null}
                  </td>
                  <td className="py-1.5 pr-2 text-teal-300">{sideCell(w.buys, locale, t)}</td>
                  <td className="py-1.5 pr-2 text-red-300">
                    {sideCell(w.sells, locale, t)}
                    {w.sells.planned_10b5_1 ? <span className="block text-xs text-gray-500">{t('research.insidersV2.planned', { count: w.sells.planned_10b5_1 })}</span> : null}
                  </td>
                  <td className={`py-1.5 font-medium ${w.net_value > 0 ? 'text-teal-300' : w.net_value < 0 ? 'text-red-300' : 'text-gray-300'}`}>{compactUsd(w.net_value, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {excluded.length ? (
          <p className="mt-2 text-xs text-gray-500">
            {t('research.insidersV2.excludedTitle')} {excluded.map(([nature, n]) => `${n} ${t(NATURE_KEYS[nature as InsiderNature] ?? NATURE_KEYS.otra).toLowerCase()}`).join(' · ')}
          </p>
        ) : null}
        {summary.late.filings ? <p className="mt-1 text-xs text-gray-500">{t('research.insidersV2.lateLine', { late: summary.late.late, filings: summary.late.filings })}</p> : null}
      </section>
      {summary.clusters.length ? (
        <section>
          <h3 className="mb-1 text-sm font-semibold text-gray-200">{t('research.insidersV2.clustersTitle')}</h3>
          <ul className="space-y-1 text-sm text-gray-300">
            {summary.clusters.map((c) => (
              <li key={c.start}>
                {t('research.insidersV2.cluster', { start: fmtDate(c.start, locale), end: fmtDate(c.end, locale), insiders: c.insiders, value: compactUsd(c.value, locale) })}
                <span className="block text-xs text-gray-500">{c.names.join(', ')}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {summary.first_buys.length ? (
        <section>
          <h3 className="mb-1 text-sm font-semibold text-gray-200">{t('research.insidersV2.firstBuysTitle')}</h3>
          <ul className="space-y-1 text-sm text-gray-300">
            {summary.first_buys.slice(0, 5).map((f) => (
              <li key={`${f.insider}-${f.tx_date}`}>
                {t(f.kind === 'desde_compra_previa' ? 'research.insidersV2.firstBuy' : 'research.insidersV2.firstBuyNoPrior', { insider: f.insider ?? '—', years: fmtNumber(f.years ?? 0, locale, 1), date: fmtDate(f.tx_date, locale) })}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section>
        <h3 className="mb-2 text-sm font-semibold text-gray-200">{market.length ? t('research.insidersV2.recentMarketTitle') : t('research.insidersV2.recentTitle')}</h3>
        <ul className="grid gap-2 md:grid-cols-2">
          {rows.map((row, index) => <RowCard key={`${row.accession_number}-${index}`} locale={locale} row={row} />)}
        </ul>
        {(summary.transactions_total ?? summary.transactions.length) > rows.length ? (
          <p className="mt-2 text-xs text-gray-500">
            {t('research.insidersV2.showing', { shown: rows.length, total: summary.transactions_total ?? rows.length })}{' '}
            <Link className="text-teal-300 underline underline-offset-2" href={`/insider?ticker=${encodeURIComponent(ticker)}`}>Form 4 →</Link>
          </p>
        ) : null}
      </section>
      <p className="text-xs text-gray-500">
        {t('research.insidersV2.footer', { source: summary.source, filings: summary.coverage?.filings ?? 0, from: fmtDate(summary.coverage?.first_filing ?? null, locale) })}
      </p>
    </div>
  );
}
