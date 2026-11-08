import Link from 'next/link';

import { districtLabel, fmtIsoDate } from '@/components/research/PoliticiansSection';
import { Badge } from '@/components/ui/badge';
import { DEFAULT_LOCALE, intlLocale, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { compactUsd, partyTone, type PoliticianCard } from '@/lib/research/insiders-politicians';

const PARTY_KEYS = {
  D: 'insider.politicians.parties.D',
  R: 'insider.politicians.parties.R',
  I: 'insider.politicians.parties.I',
} as const;

/** Ficha de un político en /politicos: operaciones, puntualidad frente a 45 días y tickers más operados. */
export function PoliticianCardView({ card, locale = DEFAULT_LOCALE }: { card: PoliticianCard; locale?: Locale }) {
  const t = createTranslator(locale);
  const intl = intlLocale(locale);
  const pct = card.on_time_pct;
  return (
    <li className="rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="politician-card">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-gray-100">{card.member ?? '—'}</h2>
        {card.party ? <Badge className={partyTone(card.party)} variant="outline">{t(PARTY_KEYS[card.party])}</Badge> : null}
      </div>
      <p className="text-xs text-gray-500">{t('insider.politicians.houseLabel')} · {districtLabel(card.state_district)}</p>
      <p className="mt-2 text-sm text-gray-300">{t('insider.politicians.tradesTickers', { trades: card.trades, tickers: card.tickers })}</p>
      <p className="text-xs text-gray-400">{t('insider.politicians.lastTrade', { date: fmtIsoDate(card.last_trade, locale) })}</p>
      <p className={`mt-1 text-xs ${card.late ? 'text-amber-300' : 'text-gray-500'}`}>{t('insider.politicians.lateCounts', { late: card.late, late30: card.late_over_30 })}</p>
      <div className="mt-2">
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span>{pct === null ? t('insider.politicians.noDates') : t('insider.politicians.onTime', { pct: new Intl.NumberFormat(intl, { maximumFractionDigits: 1 }).format(pct) })}</span>
        </div>
        <div aria-hidden="true" className="mt-1 h-1.5 w-full rounded-full bg-gray-800">
          <div className="h-1.5 rounded-full bg-teal-400" style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%` }} />
        </div>
      </div>
      {card.top_tickers.length ? (
        <div className="mt-3">
          <p className="text-xs text-gray-500">{t('insider.politicians.topTickers')}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {card.top_tickers.map((tk) => (
              <Link className="rounded border border-gray-800 px-2 py-0.5 text-xs text-gray-200 hover:border-teal-700" href={`/research/${encodeURIComponent(tk.ticker)}?view=seguimiento#politicos`} key={tk.ticker}>
                {tk.ticker} <span className="text-gray-500">{tk.trades}</span>
              </Link>
            ))}
          </div>
        </div>
      ) : null}
      <p className="mt-3 text-xs text-gray-500">{t('insider.politicians.volume', { range: card.trades ? (card.volume_max === null ? `> ${compactUsd(card.volume_min, intl)}` : `${compactUsd(card.volume_min, intl)} – ${compactUsd(card.volume_max, intl)}`) : '—' })}</p>
      {card.scanned_filings ? <p className="text-xs text-gray-500">{t('insider.politicians.scanned', { count: card.scanned_filings })}</p> : null}
    </li>
  );
}

