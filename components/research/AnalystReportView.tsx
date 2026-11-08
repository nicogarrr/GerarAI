import Link from 'next/link';

import DcaWatchCard from '@/components/watchlist/DcaWatchCard';
import { SotpBreakdownView } from '@/components/research/SotpBreakdownSection';
import { fairValueRange, thesisRisks, userEstimates, vsPrice, type ReportCell, type ReportInputs, type ReportPeriod } from '@/lib/research/analyst-report';
import { thesisCatalystLabel } from '@/lib/research/catalyst-label';
import { cleanThesisText } from '@/lib/research/thesis-text';
import { readingSections } from '@/lib/research/thesis-reading-sections';
import { readableInk } from '@/lib/dca/readable-ink';
import { valuationSummaryText } from '@/lib/research/valuation-summary';
import type { Formatters } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

type T = TranslateFn;

const BOX = 'min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 break-inside-avoid';
const H2 = 'mb-3 border-b border-gray-800 pb-1 text-sm font-semibold uppercase tracking-wide text-teal-300';

/**
 * «Informe» de una empresa con formato de nota de analista: cabecera (nivel
 * DCA y rango de valor justo, nunca una recomendación), datos de mercado,
 * cifras reales y estimaciones del usuario (marcadas como suyas), resumen y
 * puntos clave de su tesis publicada, desglose por partes con sus escenarios,
 * las líneas de honestidad del valor justo, riesgos y la tesis completa.
 * Puro: todo llega ya leído (ver app/(root)/research/[ticker]/informe).
 */
export function AnalystReportView({ data, t, fmt, locale }: { data: ReportInputs; t: T; fmt: Formatters; locale: Locale }) {
  const { report, card, fair, thesis, sotp, honesty, keyStats, shorts } = data;
  const ticker = data.ticker;
  const market = report?.market;
  const currency = market?.currency ?? fair?.currency ?? sotp?.model?.currency ?? null;
  const na = t('research.informe.na');
  const money = (v: number | null | undefined, digits = 2) => (v == null ? na : currency ? fmt.formatMoney(v, currency, { minimumFractionDigits: digits, maximumFractionDigits: digits }) : fmt.formatNumber(v, { maximumFractionDigits: digits }));
  const big = (v: number | null | undefined) => (v == null ? na : currency ? fmt.formatMoneyCompact(v, currency) : fmt.formatCompact(v));
  const count = (v: number | null | undefined) => (v == null ? na : fmt.formatCompact(v));
  const pct = (v: number | null) => (v == null ? na : fmt.formatPercent(v, { fromRatio: true, digits: 1, signDisplay: 'always' }));
  const price = market?.price ?? card?.current?.close ?? sotp?.price ?? null;
  const priceDate = market?.price_date ?? card?.current?.signal_date ?? sotp?.price_as_of ?? null;
  const range = fairValueRange(fair, thesis, data.engineRange);
  const zone = card?.available ? card.current : undefined;
  const sections = thesis ? readingSections(thesis) : [];
  const risks = thesisRisks(thesis, sections);
  const mine = userEstimates(sotp);
  const enc = encodeURIComponent(ticker);
  const r52 = keyStats?.range_52w ?? null;
  const shortRatio = shorts?.data?.short_volume_ratio ?? null;
  // La tasa base ya va dentro del desglose por partes cuando lo hay: no se repite.
  const honestyLines = [honesty.trackRecord, sotp ? null : honesty.baseRate, honesty.sbc, honesty.impliedGrowth].filter((x): x is string => Boolean(x));

  return (
    <article className="print-document mx-auto flex w-full min-w-0 max-w-4xl flex-col gap-4" data-testid="analyst-report">
      <header className="rounded-xl border border-gray-800 bg-surface-1 p-4 break-inside-avoid">
        <p className="text-xs uppercase tracking-wide text-gray-400">{t('research.informe.kicker', { date: fmt.formatMarketDate(data.today) })}</p>
        <h1 className="mt-1 text-2xl font-semibold text-gray-100">{report?.company ?? ticker} <span className="text-gray-400">({ticker})</span></h1>
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <p className="text-xs text-gray-500">{t('research.informe.dcaLevel')}</p>
            {zone ? (
              <p className="mt-1"><span className="inline-block rounded px-2 py-0.5 text-sm font-semibold" data-testid="informe-dca" style={{ backgroundColor: zone.color, color: readableInk(zone.color, zone.fg) }}>{zone.label}</span>
                <span className="block text-xs text-gray-400">{zone.zone} · {t('research.informe.monthsInZone', { n: zone.months_in_zone })}</span></p>
            ) : <p className="mt-1 text-gray-300">{na}</p>}
          </div>
          <div>
            <p className="text-xs text-gray-500">{t('research.informe.fairValue')}</p>
            <p className="mt-1 text-lg font-semibold text-gray-100" data-testid="informe-fair">{fair?.value != null ? money(fair.value) : t('research.informe.noFairValue')}</p>
            <p className="text-xs text-gray-400">{fair?.label ? valuationSummaryText(fair.label, locale) : ''}{fair?.as_of ? ` · ${fmt.formatMarketDate(fair.as_of)}` : ''}</p>
            {fair?.value == null && fair?.reason ? <p className="text-xs text-gray-400">{valuationSummaryText(fair.reason, locale)}</p> : null}
          </div>
          <div>
            <p className="text-xs text-gray-500">{t('research.informe.fairRange')}</p>
            <p className="mt-1 text-gray-100" data-testid="informe-range">{range ? `${money(range.low)} – ${money(range.high)}` : na}</p>
            <p className="text-xs text-gray-400">{range ? (range.source === 'thesis' ? t('research.informe.rangeThesis') : t('research.informe.rangeEngine')) : ''}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">{t('research.informe.price')}</p>
            <p className="mt-1 text-lg font-semibold text-gray-100">{money(price)}</p>
            <p className="text-xs text-gray-400">{priceDate ? fmt.formatMarketDate(priceDate) : ''}{fair?.value != null && price ? ` · ${t('research.informe.fairVsPrice', { pct: pct(vsPrice(fair.value, price)) })}` : ''}</p>
          </div>
        </div>
        <p className="mt-3 text-xs text-gray-500">{t('research.informe.notARating')}</p>
        <div className="mt-3 flex flex-wrap gap-3 text-sm print:hidden">
          <Link className="inline-flex min-h-[44px] items-center text-teal-300 sm:min-h-0" href={`/research/${enc}`}>{t('research.informe.back')}</Link>
          {thesis ? <a className="inline-flex min-h-[44px] items-center text-teal-300 sm:min-h-0" href={`/api/thesis/${enc}/pdf`} download>{t('research.informe.thesisPdf')}</a> : null}
        </div>
      </header>

      <section aria-labelledby="informe-mercado" className={BOX}>
        <h2 className={H2} id="informe-mercado">{t('research.informe.marketData')}</h2>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm" data-testid="informe-market">
          <Item label={t('research.informe.price')} value={money(price)} />
          <Item label={t('research.informe.marketCap')} value={big(market?.market_cap)} note={market?.market_cap_basis === 'shares_diluted' ? t('research.informe.marketCapDiluted') : undefined} />
          <Item label={t('research.informe.range52w')} value={r52 ? `${money(r52.low)} – ${money(r52.high)}` : na} />
          <Item label={t('research.informe.avgVolume')} value={count(market?.avg_volume)} note={market?.avg_volume ? t('research.informe.avgVolumeNote', { n: market.avg_volume_sessions }) : undefined} />
          <Item label={t('research.informe.shortVolume')} value={shortRatio == null ? na : fmt.formatPercent(shortRatio, { fromRatio: true, digits: 1 })} note={shortRatio == null ? undefined : t('research.informe.shortVolumeNote')} />
          <Item label={t('research.informe.ev')} value={big(market?.enterprise_value)} note={market?.enterprise_value == null ? evReason(t, market?.enterprise_value_reason) : t('research.informe.evNote')} />
          <Item label={t('research.informe.sharesOut')} value={count(market?.shares_outstanding?.value)} note={market?.shares_outstanding?.period_end ? fmt.formatMarketDate(market.shares_outstanding.period_end) : undefined} />
          <Item label={t('research.informe.sharesDiluted')} value={count(market?.shares_diluted?.value)} note={sotp?.result?.shares_diluted ? t('research.informe.sharesSotp', { n: fmt.formatNumber(sotp.result.shares_diluted, { maximumFractionDigits: 1 }) }) : undefined} />
          <Item label={t('research.informe.cash')} value={big(market?.cash?.value)} />
          <Item label={t('research.informe.debt')} value={big(market?.total_debt?.value)} />
        </dl>
      </section>

      <section aria-labelledby="informe-estimaciones" className={BOX}>
        <h2 className={H2} id="informe-estimaciones">{t('research.informe.estimates')}</h2>
        <PeriodTable t={t} fmt={fmt} big={big} title={t('research.informe.annual')} rows={report?.estimates.annual ?? []} kind="FY" />
        <PeriodTable t={t} fmt={fmt} big={big} title={t('research.informe.quarterly')} rows={report?.estimates.quarterly ?? []} kind="Q" />
        <p className="mt-2 text-xs text-gray-500">{t('research.informe.actualsNote')}</p>
        <div className="mt-3 rounded-lg border border-amber-700/60 bg-amber-950/30 p-3 text-sm" data-testid="informe-user-estimates">
          <p className="text-xs font-semibold text-amber-200">{mine?.author ? t('research.informe.userEstimatesBy', { author: mine.author }) : t('research.informe.userEstimates')}</p>
          {mine ? (
            <p className="mt-1 text-gray-200">{t('research.informe.userEstimatesLine', { year: String(mine.year), revenue: `${fmt.formatNumber(mine.revenue ?? 0, { maximumFractionDigits: 0 })} M`, ebitda: `${fmt.formatNumber(mine.ebitda ?? 0, { maximumFractionDigits: 0 })} M` })}</p>
          ) : <p className="mt-1 text-gray-400">{t('research.informe.userEstimatesNone')}</p>}
          <p className="mt-1 text-xs text-amber-200/80">{t('research.informe.userEstimatesLabel')}</p>
        </div>
      </section>

      <section aria-labelledby="informe-resumen" className={BOX}>
        <h2 className={H2} id="informe-resumen">{t('research.informe.summary')}</h2>
        {thesis ? (
          <>
            <p className="text-xs text-gray-500">{t('research.informe.thesisVersion', { version: thesis.version, date: thesis.created_at ? fmt.formatMarketDate(thesis.created_at) : na })}</p>
            {thesis.executive_summary ? <p className="mt-2 text-sm leading-relaxed text-gray-200">{cleanThesisText(thesis.executive_summary)}</p> : null}
            <h3 className="mt-4 text-sm font-semibold text-gray-100">{t('research.informe.keyPoints')}</h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-200" data-testid="informe-key-points">
              {thesis.hypothesis ? <li>{cleanThesisText(thesis.hypothesis)}</li> : null}
              {(thesis.catalysts ?? []).map((c, i) => <li key={`c-${i}`}>{c.label ? thesisCatalystLabel(c.label, locale, t) : t('research.informe.catalyst')}{c.date ? ` (${fmt.formatMarketDate(c.date)})` : ''}</li>)}
            </ul>
          </>
        ) : <p className="text-sm text-gray-400">{t('research.informe.noThesis')}</p>}
        <Link className="mt-3 inline-flex min-h-[44px] items-center text-sm text-teal-300 print:hidden sm:min-h-0" href={`/research/${enc}?view=tesis#tesis-actual`}>{t('research.informe.editThesis')}</Link>
      </section>

      <section aria-labelledby="informe-valoracion" className={BOX}>
        <h2 className={H2} id="informe-valoracion">{t('research.informe.valuation')}</h2>
        {honestyLines.length ? <ul className="mb-3 space-y-1 text-xs text-gray-300" data-testid="informe-honesty">{honestyLines.map((line) => <li className="rounded-lg border border-gray-800 bg-gray-900/40 p-2" key={line}>{line}</li>)}</ul> : null}
        {sotp ? <SotpBreakdownView data={sotp} t={t} fmt={fmt} locale={locale} ticker={ticker} editable={false} /> : <p className="text-sm text-gray-400">{t('research.informe.noSotp')}</p>}
        <Link className="mt-3 inline-flex min-h-[44px] items-center text-sm text-teal-300 print:hidden sm:min-h-0" href={`/research/${enc}?view=valoracion#desglose-partes`}>{t('research.informe.editSotp')}</Link>
      </section>

      {card ? (
        <section aria-labelledby="informe-dca" className={BOX}>
          <h2 className={H2} id="informe-dca">{t('research.informe.dcaTitle')}</h2>
          <DcaWatchCard data={card} ti={t} locale={locale} />
        </section>
      ) : null}

      <section aria-labelledby="informe-riesgos" className={BOX}>
        <h2 className={H2} id="informe-riesgos">{t('research.informe.risks')}</h2>
        {risks.criteria.length || risks.sections.length ? (
          <>
            {risks.criteria.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-gray-200" data-testid="informe-risk-criteria">{risks.criteria.map((c, i) => <li key={i}>{cleanThesisText(c)}</li>)}</ul> : null}
            {risks.sections.map((s, i) => <div className="mt-3" key={`r-${i}`}><h3 className="text-sm font-semibold text-gray-100">{s.titulo}</h3>{s.parrafos.map((p, j) => <p className="mt-1 text-sm text-gray-300" key={j}>{cleanThesisText(p)}</p>)}</div>)}
          </>
        ) : <p className="text-sm text-gray-400">{t('research.informe.noRisks')}</p>}
      </section>

      {sections.length ? (
        <section aria-labelledby="informe-tesis" className={BOX}>
          <h2 className={H2} id="informe-tesis">{t('research.informe.fullThesis')}</h2>
          {sections.map((s, i) => <div className="mt-3 first:mt-0" key={`s-${i}`}><h3 className="text-sm font-semibold text-gray-100">{s.titulo}</h3>{s.parrafos.map((p, j) => <p className="mt-1 text-sm leading-relaxed text-gray-300" key={j}>{cleanThesisText(p)}</p>)}</div>)}
        </section>
      ) : null}

      <footer className="px-1 pb-4 text-xs text-gray-500">{t('research.informe.footer', { date: fmt.formatMarketDate(data.today) })}</footer>
    </article>
  );
}

function Item({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="min-w-0"><dt className="text-xs text-gray-500">{label}</dt><dd className="text-gray-100">{value}</dd>{note ? <dd className="text-xs text-gray-500">{note}</dd> : null}</div>;
}

function evReason(t: T, reason: string | null | undefined): string | undefined {
  switch (reason) {
    case 'missing_cash_or_debt': return t('research.informe.evMissing');
    case 'cash_debt_different_dates': return t('research.informe.evDates');
    case 'currency_mismatch': return t('research.informe.evCurrency');
    default: return undefined;
  }
}

function cellText(cell: ReportCell, big: (v: number | null | undefined) => string): string {
  if (!cell || cell.value == null) return '—';
  const marks = `${cell.derived_q4 ? '¹' : ''}${cell.basis === 'source_ebitda' ? '²' : ''}`;
  return `${big(cell.value)}${marks}`;
}

function PeriodTable({ t, fmt, big, title, rows, kind }: { t: T; fmt: Formatters; big: (v: number | null | undefined) => string; title: string; rows: ReportPeriod[]; kind: 'FY' | 'Q' }) {
  if (!rows.length) return <p className="mb-2 text-sm text-gray-400">{title}: {t('research.informe.noActuals')}</p>;
  const head = (row: ReportPeriod) => {
    const year = fmt.formatMarketDate(row.period_end, { year: '2-digit', month: 'short' });
    return kind === 'FY' ? t('research.informe.fyHead', { date: year }) : `${row.fiscal_quarter} · ${year}`;
  };
  return (
    <div className="mb-3 overflow-x-auto" role="region" aria-label={title} tabIndex={0}>
      <table className="w-full text-right text-sm">
        <caption className="mb-1 text-left text-xs font-semibold text-gray-400">{title}</caption>
        <thead className="text-xs text-gray-500"><tr>
          <th className="py-1 text-left" scope="col">{t('research.informe.period')}</th>
          <th className="py-1" scope="col">{t('research.informe.revenue')}</th>
          <th className="py-1" scope="col">{t('research.informe.ebitda')}</th>
        </tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr className="border-t border-gray-800" key={row.period_end}>
              <th className="whitespace-nowrap py-1 text-left font-normal text-gray-300" scope="row">{head(row)}</th>
              <td className="whitespace-nowrap py-1 pl-2 text-gray-100">{cellText(row.revenue, big)}</td>
              <td className="whitespace-nowrap py-1 pl-2 text-gray-100">{cellText(row.ebitda, big)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
