import type { ReactNode } from 'react';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { alignmentNumber, alignmentUrl, type AlignmentEvidence, type AlignmentRatio, type AlignmentTrade, type ManagementAlignment } from '@/lib/research/management-alignment';

function Evidence({ fact, sharesLabel }: { fact: AlignmentEvidence; sharesLabel: string }) {
  const href = alignmentUrl(fact.url);
  if (!href) return null;
  return <a className="underline underline-offset-2" href={href} rel="noopener noreferrer" target="_blank">{alignmentNumber(fact.value, fact.unit === 'shares' ? sharesLabel : fact.unit)}</a>;
}

function Ratio({ data }: { data: AlignmentRatio }) {
  const sources = data.sources ?? [];
  if (data.value === null || !sources.length || sources.some(s => !alignmentUrl(s.url))) return null;
  return <a className="underline underline-offset-2" href={sources[0].url} rel="noopener noreferrer" target="_blank">{alignmentNumber(data.value, '%')}</a>;
}

function TradeSources({ trades, children }: { trades: AlignmentTrade[]; children: ReactNode }) {
  const first = trades.find(t => alignmentUrl(t.url));
  return first ? <a className="underline" href={first.url!} rel="noopener noreferrer" target="_blank">{children}</a> : <span>{children}</span>;
}

export function ManagementAlignmentSection({ data, locale = DEFAULT_LOCALE }: { data: ManagementAlignment; locale?: Locale }) {
  const t = createTranslator(locale);
  const latest = data.years?.at(-1);
  const annual = data.insiders?.find(w => w.months === 12);
  const sharesLabel = t('research.managementAlignment.sharesUnit');
  if (data.status !== 'ok') return <p className="text-sm text-amber-300" role="status">{data.reason}</p>;
  const capitalWarnings = [...new Set((data.years ?? []).flatMap(r => r.quality_warnings ?? r.warnings))];
  const missingFields = [...new Set((data.years ?? []).flatMap(r => [!r.sbc ? 'SBC' : '', !r.repurchases ? t('research.managementAlignment.buybacks') : '', r.sbc_revenue_pct.value === null ? t('research.managementAlignment.sbcRevenue') : '', r.sbc_fcf_pct.value === null ? t('research.managementAlignment.sbcFcf') : ''].filter(Boolean)))];
  const partial = missingFields.length > 0;
  return <div className="grid min-w-0 gap-4 text-sm">
    <p className="text-gray-400">{t('research.managementAlignment.cutoff', { date: data.as_of ?? '' })}</p>
    {data.stale && <p className="text-amber-300" role="status">{t('research.managementAlignment.stale')}</p>}
    <div className="grid gap-2 [overflow-wrap:anywhere]">
      {latest && latest.shares_change_pct.value !== null && <p>{latest.change_label}: <Ratio data={latest.shares_change_pct} /></p>}
      {latest?.sbc && <p>{t('research.managementAlignment.sbcYear', { year: latest.year })}: <Evidence fact={latest.sbc} sharesLabel={sharesLabel} /></p>}
      {annual?.status === 'ok' && annual.net_value !== null && <p>{t('research.managementAlignment.insiderSummary')}: <TradeSources trades={Object.values(annual.groups).flat()}>{alignmentNumber(annual.net_value, 'USD')}</TradeSources></p>}
    </div>
    <details className="min-w-0 rounded-lg border border-gray-700 p-4">
      <summary className="cursor-pointer font-medium">{t('research.managementAlignment.capital')}</summary>
      {!data.years?.length ? <p className="mt-3 text-amber-300" role="status">{data.dilution_reason}</p> : <>
        {(partial || capitalWarnings.length > 0) && <p className="mt-3 text-amber-300" role="status">{[partial ? t('research.managementAlignment.partialCapital', { fields: missingFields.join(', ') }) : '', ...capitalWarnings].filter(Boolean).join(' ')}</p>}
        {data.years.map(row => <div className="mt-4 grid gap-2 border-t border-gray-800 pt-3 [overflow-wrap:anywhere]" key={row.year}>
          <h4 className="font-medium">{t('research.managementAlignment.fiscalYear', { year: row.year })} · {row.shares?.date ?? row.sbc?.date ?? row.repurchases?.date}</h4>
          {row.shares && <p>{row.share_basis === 'shares_diluted' ? t('research.managementAlignment.diluted') : row.share_basis === 'dei' ? t('research.managementAlignment.coverShares') : t('research.managementAlignment.shares')}: <Evidence fact={row.shares} sharesLabel={sharesLabel} /></p>}
          {row.shares_change_pct.value !== null && <p>{row.change_label}: <Ratio data={row.shares_change_pct} /></p>}
          {row.sbc && <p>SBC: <Evidence fact={row.sbc} sharesLabel={sharesLabel} /></p>}
          {row.sbc_revenue_pct.value !== null && <p>{t('research.managementAlignment.sbcRevenue')}: <Ratio data={row.sbc_revenue_pct} /></p>}
          {row.sbc_fcf_pct.value !== null && <p>{t('research.managementAlignment.sbcFcf')}: <Ratio data={row.sbc_fcf_pct} /></p>}
          {row.repurchases && <p>{row.repurchases_label}: <Evidence fact={row.repurchases} sharesLabel={sharesLabel} /></p>}
        </div>)}
      </>}
    </details>
    <details className="min-w-0 rounded-lg border border-gray-700 p-4">
      <summary className="cursor-pointer font-medium">{t('research.managementAlignment.insiders')}</summary>
      <p className="mt-3 text-gray-400">{t('research.managementAlignment.planNote')}</p>
      {data.insiders?.map(window => {
        const all = Object.values(window.groups).flat();
        const invalid = all.filter(tx => tx.reported_value);
        const incomplete = window.net_value === null || window.discretionary_net_value === null;
        return <div className="mt-4 grid gap-2 border-t border-gray-800 pt-3 [overflow-wrap:anywhere]" key={window.months}>
          <h4 className="font-medium">{t('research.managementAlignment.window', { months: window.months })} · {window.from} - {window.to}</h4>
          {window.status !== 'ok' ? <p className="text-amber-300" role="status">{window.reason}</p> : <>
            {(incomplete || window.warnings.length > 0) && <p className="text-amber-300" role="status">{[incomplete ? t('research.managementAlignment.partialInsider') : '', ...window.warnings].filter(Boolean).join(' ')}</p>}
            <p><TradeSources trades={all}>{t('research.managementAlignment.buyCount', { count: window.groups.buys.length })}</TradeSources> / <TradeSources trades={all}>{t('research.managementAlignment.sellCount', { count: all.length - window.groups.buys.length })}</TradeSources></p>
            <p><TradeSources trades={window.groups.planned_sales.length ? window.groups.planned_sales : all}>{t('research.managementAlignment.plannedCount', { count: window.groups.planned_sales.length })}</TradeSources>; <TradeSources trades={window.groups.unplanned_sales.length ? window.groups.unplanned_sales : all}>{t('research.managementAlignment.unplannedCount', { count: window.groups.unplanned_sales.length })}</TradeSources>; <TradeSources trades={window.groups.unknown_sales.length ? window.groups.unknown_sales : all}>{t('research.managementAlignment.unknownCount', { count: window.groups.unknown_sales.length })}</TradeSources></p>
            {window.net_value !== null && <p>{t('research.managementAlignment.netTotal')}: <TradeSources trades={all}>{alignmentNumber(window.net_value, 'USD')}</TradeSources></p>}
            {window.discretionary_net_value !== null && <p>{t('research.managementAlignment.netUnplanned')}: <TradeSources trades={all}>{alignmentNumber(window.discretionary_net_value, 'USD')}</TradeSources></p>}
          </>}
          {invalid.map((tx, index) => <p className="text-amber-300" key={`${tx.accession}-${index}`}><TradeSources trades={[tx]}>{t('research.managementAlignment.reviewAmount', { value: tx.reported_value! })}</TradeSources></p>)}
        </div>;
      })}
    </details>
  </div>;
}
