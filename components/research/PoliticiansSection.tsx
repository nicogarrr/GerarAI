import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { DEFAULT_LOCALE, intlLocale, type Locale } from '@/lib/i18n/locale';
import type { TranslationKey } from '@/lib/i18n/t';
import { createTranslator } from '@/lib/i18n/translate';
import { amountRange, partyTone, type PoliticianTickerTrades, type PoliticianTrade } from '@/lib/research/insiders-politicians';

const MAX_ROWS = 12;

const TYPE_KEYS = {
  compra: 'research.politicos.type.compra',
  venta: 'research.politicos.type.venta',
  venta_parcial: 'research.politicos.type.ventaParcial',
  canje: 'research.politicos.type.canje',
  otra: 'research.politicos.type.otra',
} as const satisfies Record<PoliticianTrade['type_label'], TranslationKey>;

export function fmtIsoDate(value: string | null, locale: Locale): string {
  if (!value) return '—';
  const [y, m, d] = value.split('-').map(Number);
  return new Intl.DateTimeFormat(intlLocale(locale), { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m - 1, d));
}

export function districtLabel(stateDistrict: string | null): string {
  if (!stateDistrict) return '—';
  const state = stateDistrict.slice(0, 2);
  const district = stateDistrict.slice(2);
  return district ? `${state}-${district}` : state;
}

/**
 * Quién de la Cámara de EE. UU. operó el ticker (PTR del STOCK Act), con el
 * rango de importe declarado y los días de retraso frente a los 45 de la ley.
 */
export function PoliticiansSection({ ticker, data, locale = DEFAULT_LOCALE }: { ticker: string; data: PoliticianTickerTrades | null; locale?: Locale }) {
  const t = createTranslator(locale);
  const intl = intlLocale(locale);
  const footer = (
    <p className="text-xs text-gray-500">
      {t('research.politicos.footer')}{' '}
      <Link className="text-teal-300" href="/politicos">{t('research.politicos.seeAll')}</Link>
    </p>
  );
  if (data === null) return <p className="text-sm text-gray-400" role="status">{t('research.politicos.loadError')}</p>;
  if (data.status !== 'ok') return <div className="grid gap-2"><p className="text-sm text-gray-400" role="status">{t('research.politicos.empty', { ticker })}</p>{footer}</div>;
  return (
    <div className="grid gap-4" data-testid="politicians-section">
      <p className="text-sm text-gray-300">{t('research.politicos.summary', { trades: data.trades_total, members: data.members.length, buys: data.buys, sells: data.sells })}</p>
      <ul className="grid gap-2 md:grid-cols-2">
        {data.members.slice(0, 8).map((m) => (
          <li className="rounded-lg border border-gray-800 p-3 text-sm" key={m.member_key}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-gray-100">{m.member ?? '—'}</span>
              {m.party ? <Badge className={partyTone(m.party)} variant="outline">{m.party}</Badge> : null}
              <span className="text-xs text-gray-500">{districtLabel(m.state_district)}</span>
            </div>
            <p className="mt-1 text-xs text-gray-400">{t('research.politicos.buysSells', { buys: m.buys, sells: m.sells, date: fmtIsoDate(m.last_trade, locale) })}</p>
          </li>
        ))}
      </ul>
      <ul className="grid gap-2">
        {data.trades.slice(0, MAX_ROWS).map((trade) => (
          <li className="rounded-lg border border-gray-800 p-3 text-sm" key={`${trade.doc_id}-${trade.tx_date}-${trade.amount_text}-${trade.asset}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-gray-100">{trade.member ?? '—'}</span>
              {trade.party ? <Badge className={partyTone(trade.party)} variant="outline">{trade.party}</Badge> : null}
              <Badge className={trade.type === 'P' ? 'border-teal-800 text-teal-300' : 'border-red-900 text-red-300'} variant="outline">{t(TYPE_KEYS[trade.type_label] ?? TYPE_KEYS.otra)}</Badge>
            </div>
            <p className="mt-1 text-gray-300">{amountRange(trade.amount_min, trade.amount_max, intl)}</p>
            <p className={`mt-1 text-xs ${trade.days_late ? 'text-amber-300' : 'text-gray-500'}`}>
              {t('research.politicos.tradeDates', { tx: fmtIsoDate(trade.tx_date, locale), filed: fmtIsoDate(trade.filing_date, locale) })}
              {' · '}{trade.days_late ? t('research.politicos.late', { days: trade.days_late }) : t('research.politicos.onTime')}
              {trade.source_url ? <>{' · '}<a className="text-teal-300 underline-offset-2 hover:underline" href={trade.source_url} rel="noreferrer" target="_blank">{t('research.politicos.ptr')}</a></> : null}
            </p>
          </li>
        ))}
      </ul>
      {footer}
    </div>
  );
}
