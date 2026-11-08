import { Layers } from 'lucide-react';
import Link from 'next/link';

import { MutationForm } from '@/components/forms/MutationForm';
import SotpAgentsButton from '@/components/research/SotpAgentsButton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { deleteSotpResult, saveSotpResult } from '@/lib/actions/sotp.actions';
import { formatNumberForInput, formatUserDate } from '@/lib/format';
import { getFormat, getLocale, getT } from '@/lib/i18n/server';
import { SOTP_EXTRA_DILUTION, SOTP_EXTRA_PARTS, SOTP_EXTRA_SCENARIOS, getSotp, type SotpCompaniesHouse, type SotpModel, type SotpResponse, type SotpSource, type SotpVariantKey, type SotpWhy } from '@/lib/research/sotp';

type T = Awaited<ReturnType<typeof getT>>;
type F = Awaited<ReturnType<typeof getFormat>>;

const SENS_KEYS = {
  multiples_minus_30: 'research.sotp.sens.multiplesMinus30',
  delay_2y: 'research.sotp.sens.delay2y',
  revenue_minus_50: 'research.sotp.sens.revenueMinus50',
  rate_plus_5pp: 'research.sotp.sens.ratePlus5pp',
  combined: 'research.sotp.sens.combined',
} as const;

const VARIANT_KEYS = {
  agents: 'research.sotp.variant.agents',
  user: 'research.sotp.variant.user',
  example: 'research.sotp.variant.example',
} as const;
const WHY_KEYS = {
  revenue: 'research.sotp.why.revenue',
  margin: 'research.sotp.why.margin',
  multiple: 'research.sotp.why.multiple',
  probability: 'research.sotp.why.probability',
  value: 'research.sotp.why.value',
  shares: 'research.sotp.why.shares',
} as const;

const BOX = 'rounded-lg border border-gray-800 bg-gray-900/40 p-3';
const LABEL = 'grid min-w-0 content-start gap-1 text-xs text-gray-400';

function pct(fmt: F, value: number | null | undefined, sign = true): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return fmt.formatPercent(value, { fromRatio: true, digits: 1, signDisplay: sign ? 'always' : 'auto' });
}

/**
 * «Desglose por partes» (SOTP) de la pestaña Valoración: tabla parte → valor
 * hoy → $/acción con su aritmética, escenarios, sensibilidad y, siempre al
 * lado, la tasa base medida y la etiqueta de supuestos no validados.
 */
export async function SotpBreakdownSection({ ticker, variant = null }: { ticker: string; variant?: SotpVariantKey | null }) {
  const [data, t, fmt, locale] = await Promise.all([getSotp(ticker, variant), getT(), getFormat(), getLocale()]);
  if (!data) return <p className={`${BOX} text-xs text-gray-400`} role="status">{t('research.sotp.loadError')}</p>;
  return <SotpBreakdownView data={data} t={t} fmt={fmt} locale={locale} ticker={ticker} />;
}

export function SotpBreakdownView({ data, t, fmt, locale, ticker, editable = true }: { data: SotpResponse; t: T; fmt: F; locale: 'es' | 'en'; ticker: string; editable?: boolean }) {
  const model = data.model;
  const result = data.result;
  const baseRate = data.base_rate;
  const baseRateText = locale === 'en' ? baseRate.message_en : baseRate.message_es;
  const currency = model?.currency ?? null;
  const money = (v: number) => `${fmt.formatNumber(v, { maximumFractionDigits: 0 })} M`;
  const perShare = (v: number | null | undefined) => {
    if (v === null || v === undefined) return '—';
    const opts = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
    return currency ? fmt.formatMoney(v, currency, opts) : fmt.formatNumber(v, opts);
  };
  return (
    <section aria-labelledby="sotp-title" className="min-w-0 space-y-3 rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="sotp-breakdown">
      <div className="flex flex-wrap items-center gap-2">
        <Layers aria-hidden="true" className="h-5 w-5 text-teal-300" />
        <h3 className="text-lg font-semibold text-gray-100" id="sotp-title">{t('research.sotp.title')}</h3>
        <span className="rounded-full border border-amber-700/60 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-200" data-testid="sotp-unvalidated">{data.origin === 'agents' ? t('research.sotp.unvalidatedAgents') : t('research.sotp.unvalidated')}</span>
      </div>
      <SotpVariantNav data={data} t={t} ticker={ticker} />
      {data.origin === 'example' ? <p className="text-xs text-amber-200/90">{t('research.sotp.exampleNico')} {t('research.sotp.exampleDraft', { author: model?.author ?? '—' })}</p> : null}
      {data.origin === 'agents' ? (
        <p className="text-xs text-teal-200" data-testid="sotp-agents-label">
          {t('research.sotp.agentsLabel', {
            date: data.agents?.generated_at ? formatUserDate(data.agents.generated_at, undefined, '—', locale) : '—',
            price: data.agents?.price !== null && data.agents?.price !== undefined ? perShare(data.agents.price) : '—',
          })}
        </p>
      ) : null}
      {data.origin === 'agents' && data.agents?.mostly_cash ? (
        <p className="rounded-md border border-amber-600 bg-amber-950/60 px-3 py-2 text-sm font-medium text-amber-100" data-testid="sotp-mostly-cash" role="note">
          {t('research.sotp.mostlyCash', {
            cash: perShare(data.agents.mostly_cash.cash_per_share),
            total: perShare(data.agents.mostly_cash.value_per_share),
            share: fmt.formatPercent(data.agents.mostly_cash.share, { digits: 0 }),
          })}
        </p>
      ) : null}
      {data.origin === 'agents' ? <p className="text-xs text-amber-200/90">{t('research.sotp.agentsVariance')}</p> : null}
      {data.origin === 'agents' && data.agents_stability?.unstable ? (
        <p className="rounded-md border border-amber-700/60 bg-amber-950/40 px-2 py-1 text-xs text-amber-100" data-testid="sotp-unstable">
          {t('research.sotp.unstable', {
            previous: perShare(data.agents_stability.previous_value_per_share),
            current: perShare(data.agents_stability.current_value_per_share),
            change: pct(fmt, data.agents_stability.change),
          })}
        </p>
      ) : null}
      {data.origin === 'saved' ? <p className="text-xs text-gray-400">{t('research.sotp.userLabel')}</p> : null}
      {!(data.variants ?? []).some((v) => v.key === 'agents' && v.available) ? (
        <p className="text-xs text-gray-400" data-testid="sotp-no-agents">
          {t('research.sotp.noAgents')}
          {data.agents_status?.problems?.length ? ` ${t('research.sotp.noAgentsWhy', { why: data.agents_status.problems.slice(0, 3).join(' · ') })}` : ''}
        </p>
      ) : null}
      {model?.summary ? <p className="text-sm text-gray-300" data-testid="sotp-summary">{model.summary}</p> : null}
      {data.origin === 'agents' && data.agents?.readings_differ && data.agents.readings?.length ? (
        <p className="text-xs text-amber-200/90" data-testid="sotp-readings">
          {t('research.sotp.readingsDiffer', { values: data.agents.readings.map((r) => perShare(r.value_per_share)).join(' / ') })}
        </p>
      ) : null}
      {data.origin === 'agents' && data.agents?.changed_by?.length ? (
        <p className="text-xs text-gray-400" data-testid="sotp-changed-by">{t('research.sotp.changedBy', { what: data.agents.changed_by.slice(0, 4).join(' · ') })}</p>
      ) : null}
      {model?.warnings?.length ? (
        <ul className="space-y-1 rounded-md border border-amber-800/60 bg-amber-950/30 px-2 py-1 text-xs text-amber-100" data-testid="sotp-warnings">
          {model.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      ) : null}
      {model?.unvalued?.length ? (
        <div className="text-xs text-gray-400" data-testid="sotp-unvalued">
          <p className="text-gray-300">{t('research.sotp.unvaluedTitle')}</p>
          <ul className="list-disc pl-4">
            {model.unvalued.map((u, i) => <li key={`${u.name}-${i}`}>{u.name}{u.reason ? ` — ${u.reason}` : ''}</li>)}
          </ul>
        </div>
      ) : null}
      {model?.source ? <p className="text-xs text-gray-500">{model.source}</p> : null}
      {baseRateText ? (
        <p className={`${BOX} text-xs text-gray-300`} data-testid="sotp-base-rate">
          {baseRate.applies === false ? t('research.sotp.baseRateNotApplies') : baseRate.applies === null ? t('research.sotp.baseRateUnknown') : null}
          {baseRate.applies === true ? null : ' '}
          {baseRateText}
        </p>
      ) : null}
      {model && result ? (
        <>
          <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <div className={BOX}><p className="text-xs text-gray-500">{t('research.sotp.totalPerShare')}</p><p className="text-xl font-semibold text-gray-100" data-testid="sotp-total">{perShare(result.value_per_share)}</p></div>
            <div className={BOX}><p className="text-xs text-gray-500">{t('research.sotp.vsPrice', { price: perShare(result.price) })}</p><p className="text-xl font-semibold text-gray-100">{pct(fmt, result.vs_price)}</p></div>
            <div className={BOX}><p className="text-xs text-gray-500">{t('research.sotp.discount')}</p><p className="text-sm text-gray-200">{t('research.sotp.discountValue', { rate: pct(fmt, model.discount_rate, false), years: fmt.formatNumber(result.discount_years, { maximumFractionDigits: 1 }), factor: fmt.formatNumber(result.discount_factor, { maximumFractionDigits: 4 }) })}</p></div>
            <div className={BOX}><p className="text-xs text-gray-500">{t('research.sotp.shares')}</p><p className="text-sm text-gray-200">{t('research.sotp.sharesValue', { current: fmt.formatNumber(model.shares_current, { maximumFractionDigits: 1 }), diluted: fmt.formatNumber(result.shares_diluted, { maximumFractionDigits: 1 }) })}</p></div>
          </div>
          {model.discount_rate_source ? <p className="text-xs text-gray-500">{t('research.sotp.rateSource', { source: model.discount_rate_source })}</p> : null}
          {model.dilution.length ? (
            <div className="text-xs text-gray-400">
              <p className="text-gray-300">{t('research.sotp.dilutionTitle')}</p>
              <ul className="space-y-1">
                {model.shares_why?.shares ? <li>{model.shares_why.shares}</li> : null}
                {model.dilution.map((d, i) => (
                  <li key={`${d.label}-${i}`}>
                    + {fmt.formatNumber(d.shares, { maximumFractionDigits: 1 })} M · {d.label}
                    <SotpWhyDetails assumption={d.assumption} sources={d.sources} t={t} why={d.why} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="overflow-x-auto" role="region" aria-label={t('research.sotp.tableLabel')} tabIndex={0}>
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t('research.sotp.tableLabel')}</caption>
              <thead className="text-xs uppercase text-gray-500"><tr>
                <th className="border-b border-gray-800 py-2" scope="col">{t('research.sotp.part')}</th>
                <th className="border-b border-gray-800 py-2 text-right" scope="col">{t('research.sotp.today', { currency: currency ?? '' })}</th>
                <th className="border-b border-gray-800 py-2 text-right" scope="col">{t('research.sotp.perShare')}</th>
              </tr></thead>
              <tbody>
                {result.rows.map((row, index) => (
                  <tr className="border-b border-gray-900 align-top" key={`${row.name}-${index}`}>
                    <th className="py-2 pr-2 text-left font-normal" scope="row">
                      <span className="block text-gray-200">{row.name}</span>
                      <span className="block text-xs text-gray-500">
                        {row.kind === 'operating'
                          ? t('research.sotp.arithOperating', { ebitda: money(row.ebitda ?? 0), multiple: fmt.formatNumber(row.multiple ?? 0, { maximumFractionDigits: 1 }), ev: money(row.value_at_maturity), year: String(model.valuation_year), revenue: row.revenue === null ? '—' : money(row.revenue) })
                          : t('research.sotp.arithAsset', { value: money(row.value_at_maturity) })}
                        {row.probability < 1 ? ` · ${t('research.sotp.probability', { p: pct(fmt, row.probability, false) })}` : ''}
                        {` · ÷ ${fmt.formatNumber(row.discount_factor, { maximumFractionDigits: 4 })}`}
                        {row.commercial === false ? ` · ${t('research.sotp.notCommercial')}` : ''}
                      </span>
                      <SotpWhyDetails assumption={row.assumption} sources={row.sources} t={t} why={row.why} />
                    </th>
                    <td className="py-2 text-right text-gray-300">{money(row.present_value)}</td>
                    <td className="py-2 text-right font-medium text-gray-100">{perShare(row.value_per_share)}</td>
                  </tr>
                ))}
                <tr className="font-semibold">
                  <th className="py-2 text-left text-gray-100" scope="row">{t('research.sotp.total')}<span className="block text-xs font-normal text-gray-500">{t('research.sotp.totalArith', { ev: money(result.total_value_at_maturity), multiple: result.weighted_multiple === null ? '—' : fmt.formatNumber(result.weighted_multiple, { maximumFractionDigits: 1 }) })}</span></th>
                  <td className="py-2 text-right text-gray-100">{money(result.total_present_value)}</td>
                  <td className="py-2 text-right text-gray-100">{perShare(result.value_per_share)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          {result.stated_value_per_share !== null && result.stated_gap !== null && Math.abs(result.stated_gap) >= 0.005 ? <p className="text-xs text-amber-200/90">{t('research.sotp.statedGap', { stated: perShare(result.stated_value_per_share), computed: perShare(result.value_per_share) })}</p> : null}
          {result.price_covered_by.length && result.price !== null ? <p className="text-xs text-gray-400">{t('research.sotp.priceCovered', { price: perShare(result.price), parts: result.price_covered_by.map((p) => `${p.name} (${perShare(p.value_per_share)})`).join(' + ') })}</p> : null}
          {result.scenarios.length ? (
            <div className="space-y-1">
              <h4 className="text-sm font-semibold text-gray-200">{t('research.sotp.scenarios')}</h4>
              <ul className="space-y-1 text-sm">
                {result.scenarios.map((s) => (
                  <li className={`${BOX} flex flex-wrap justify-between gap-x-3`} key={s.key}>
                    <span className="text-gray-300">{s.label}</span>
                    <span className="text-right text-gray-100">
                      {s.computed ? `${perShare(s.value_per_share)} (${pct(fmt, s.vs_price)})` : t('research.sotp.notComputed')}
                      {s.computed && s.value_per_share !== null && s.value_per_share <= 0 ? <span className="block text-xs text-amber-200/90">{t('research.sotp.belowZero')}</span> : null}
                      {s.stated_value_per_share !== null && s.stated_value_per_share !== undefined ? <span className="block text-xs text-gray-500">{t('research.sotp.stated', { value: perShare(s.stated_value_per_share) })}</span> : null}
                    </span>
                    {s.note ? <span className="basis-full text-xs text-gray-500">{s.note}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="space-y-1">
            <h4 className="text-sm font-semibold text-gray-200">{t('research.sotp.sensitivity')}</h4>
            <ul className="space-y-1 text-sm" data-testid="sotp-sensitivity">
              {result.sensitivity.map((s) => (
                <li className={`${BOX} flex flex-wrap justify-between gap-x-3`} key={s.key}>
                  <span className="text-gray-300">{s.key in SENS_KEYS ? t(SENS_KEYS[s.key as keyof typeof SENS_KEYS]) : s.label}</span>
                  <span className="text-gray-100">{perShare(s.value_per_share)} <span className="text-xs text-gray-500">({pct(fmt, s.vs_base)} · {t('research.sotp.vsPriceShort')} {pct(fmt, s.vs_price)})</span></span>
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : <p className="text-sm text-gray-400">{t('research.sotp.empty')}</p>}
      {data.origin === 'agents' && data.agents?.narrative?.sections?.length ? (
        <section aria-label={t('research.sotp.narrativeTitle')} className="space-y-3 rounded-lg border border-gray-800 bg-gray-900/40 p-3" data-testid="sotp-narrative">
          <h3 className="text-sm font-semibold text-gray-100">{t('research.sotp.narrativeTitle')}</h3>
          <p className="text-xs text-gray-500">{t('research.sotp.narrativeHint')}</p>
          {data.agents.narrative.sections.map((section) => (
            <div key={section.key} className="space-y-1">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-teal-300">{section.title}</h4>
              <p className="whitespace-pre-line text-sm leading-relaxed text-gray-300">{section.text}</p>
            </div>
          ))}
        </section>
      ) : null}
      {data.companies_house?.length ? <SotpCompaniesHouseAccounts rows={data.companies_house} t={t} fmt={fmt} /> : null}
      {editable ? <SotpAgentsButton hasProposal={(data.variants ?? []).some((v) => v.key === 'agents' && v.available)} ticker={ticker} /> : null}
      {editable ? <SotpEditor model={model} t={t} locale={locale} ticker={ticker} saved={data.origin === 'saved'} versions={data.saved?.versions ?? 0} fromAgents={data.origin === 'agents'} /> : null}
    </section>
  );
}

const CH_METRIC_KEYS = {
  revenue: 'research.sotp.chMetric.revenue',
  profit_before_tax: 'research.sotp.chMetric.profitBeforeTax',
  profit_for_year: 'research.sotp.chMetric.profitForYear',
  profit_attributable: 'research.sotp.chMetric.profitAttributable',
  total_equity: 'research.sotp.chMetric.totalEquity',
  equity_attributable: 'research.sotp.chMetric.equityAttributable',
  net_assets: 'research.sotp.chMetric.netAssets',
  cash: 'research.sotp.chMetric.cash',
  borrowings: 'research.sotp.chMetric.borrowings',
} as const;
const CH_METRICS = Object.keys(CH_METRIC_KEYS) as (keyof typeof CH_METRIC_KEYS)[];

/** Cuentas británicas escaneadas del grupo: cada cifra con su página, la línea literal y su comprobación. */
function SotpCompaniesHouseAccounts({ rows, t, fmt }: { rows: SotpCompaniesHouse[]; t: T; fmt: F }) {
  return (
    <section className={`${BOX} space-y-2`} data-testid="sotp-companies-house">
      <h4 className="text-sm font-semibold text-gray-200">{t('research.sotp.chTitle')}</h4>
      <p className="text-xs text-gray-500">{t('research.sotp.chHint')}</p>
      {rows.map((row) => (
        <div key={`${row.company_number}-${row.made_up_to}`} className="space-y-1">
          <p className="text-xs text-gray-300">
            {row.document_url ? <a className="underline" href={row.document_url} rel="noopener noreferrer" target="_blank">{row.company_name}</a> : row.company_name}
            {` (${row.company_number ?? '—'}) · ${row.made_up_to ?? '—'}`}
          </p>
          {row.figures.length ? (
            <ul className="space-y-0.5 text-xs text-gray-300">
              {CH_METRICS.flatMap((metric) => row.figures.filter((f) => f.metric === metric)).map((f) => (
                <li key={f.metric} title={f.line ?? undefined}>
                  <span className="text-gray-400">{t(CH_METRIC_KEYS[f.metric as keyof typeof CH_METRIC_KEYS])}: </span>
                  {fmt.formatNumber(f.value, { maximumFractionDigits: 1 })} {f.unit ?? f.currency ?? ''}
                  {f.page ? <>{' · '}{f.page_url ? <a className="underline" href={f.page_url} rel="noopener noreferrer" target="_blank">{t('research.sotp.chPage', { page: f.page })}</a> : t('research.sotp.chPage', { page: f.page })}</> : null}
                  {f.line ? <span className="text-gray-500">{` «${f.line}»`}</span> : null}
                  {f.basis ? <span className="text-gray-500">{` — ${f.basis}`}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
          {Object.values(row.checks ?? {}).map((c, i) => (
            <p key={i} className={`text-xs ${c.ok ? 'text-gray-500' : 'text-amber-200'}`}>{t('research.sotp.chChecks', { why: c.why })}</p>
          ))}
          {(row.rejected ?? []).map((r, i) => (
            <p key={`r-${i}`} className="text-xs text-amber-200">{t('research.sotp.chRejected', { metric: r.metric, page: r.page ?? '—', reason: r.reason ?? '—' })}</p>
          ))}
        </div>
      ))}
    </section>
  );
}

/** «¿De dónde sale?»: razón de cada cifra, supuesto explícito y fuentes (propuesta de los agentes). */
function SotpWhyDetails({ why, sources, assumption, t }: { why?: SotpWhy; sources?: SotpSource[]; assumption?: string | null; t: T }) {
  const entries = Object.entries(why ?? {}).filter(([key, text]) => key in WHY_KEYS && text) as [keyof typeof WHY_KEYS, string][];
  if (!entries.length && !sources?.length && !assumption) return null;
  return (
    <details className="mt-1 text-xs text-gray-400">
      <summary className="cursor-pointer text-teal-300">{t('research.sotp.whyTitle')}</summary>
      <ul className="mt-1 space-y-1">
        {entries.map(([key, text]) => <li key={key}><span className="text-gray-300">{t(WHY_KEYS[key])}:</span> {text}</li>)}
        {assumption ? <li className="text-amber-200/90">{assumption}</li> : null}
        {sources?.length ? (
          <li>
            <span className="text-gray-300">{t('research.sotp.sources')}:</span>{' '}
            {sources.map((src, i) => (
              <span key={`${src.label}-${i}`}>
                {i ? ' · ' : ''}
                {src.url ? (src.url.startsWith('/') ? <Link className="underline" href={src.url}>{src.label}</Link> : <a className="underline" href={src.url} rel="noreferrer" target="_blank">{src.label}</a>) : src.label}
                {src.date ? ` (${src.date})` : ''}
              </span>
            ))}
          </li>
        ) : null}
      </ul>
    </details>
  );
}

function SotpVariantNav({ data, t, ticker }: { data: SotpResponse; t: T; ticker: string }) {
  const variants = (data.variants ?? []).filter((v) => v.available);
  if (variants.length < 2) return null;
  return (
    <nav aria-label={t('research.sotp.variantNav')} className="flex flex-wrap gap-2 text-xs">
      {variants.map((v) => {
        const current = v.key === data.variant;
        return (
          <Link
            aria-current={current ? 'true' : undefined}
            className={`inline-flex min-h-11 items-center rounded-full border px-3 sm:min-h-0 sm:py-1 ${current ? 'border-teal-500 bg-teal-950/40 text-teal-200' : 'border-gray-700 text-gray-300'}`}
            href={`/research/${encodeURIComponent(ticker)}?view=valuation&sotp=${v.key}#desglose-partes`}
            key={v.key}
          >
            {t(VARIANT_KEYS[v.key])}{v.key === data.default_variant ? ` · ${t('research.sotp.variantDefault')}` : ''}
          </Link>
        );
      })}
    </nav>
  );
}

function SotpEditor({ model, t, locale, ticker, saved, versions, fromAgents = false }: { model?: SotpModel; t: T; locale: 'es' | 'en'; ticker: string; saved: boolean; versions: number; fromAgents?: boolean }) {
  const v = (n: number | null | undefined, scale = 1) => (n === null || n === undefined ? '' : formatNumberForInput(n * scale, locale));
  const parts = [...(model?.parts ?? []), ...Array.from({ length: SOTP_EXTRA_PARTS }, () => null)];
  const dilution = [...(model?.dilution ?? []), ...Array.from({ length: SOTP_EXTRA_DILUTION }, () => null)];
  const scenarios = [...(model?.scenarios ?? []), ...Array.from({ length: SOTP_EXTRA_SCENARIOS }, () => null)];
  const counts = { parts: parts.length, dilution: dilution.length, scenarios: scenarios.length };
  return (
    <details className={BOX}>
      <summary className="flex min-h-11 cursor-pointer items-center text-sm font-medium text-teal-300">{model ? t('research.sotp.edit') : t('research.sotp.create')}{saved ? ` · ${t('research.sotp.versions', { count: versions })}` : ''}</summary>
      <MutationForm action={saveSotpResult.bind(null, ticker, counts)} className="mt-3 grid gap-4" successMessage={t('research.sotp.saved')}>
        <p className="text-xs text-gray-500">{t('research.sotp.unitsHint')}</p>
        {fromAgents ? <p className="text-xs text-amber-200/90">{t('research.sotp.editAgentsHint')}</p> : null}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <label className={LABEL}><span>{t('research.sotp.baseYear')}</span><Input name="base_year" inputMode="numeric" defaultValue={v(model?.base_year ?? new Date().getFullYear())} required /></label>
          <label className={LABEL}><span>{t('research.sotp.valuationYear')}</span><Input name="valuation_year" inputMode="numeric" defaultValue={v(model?.valuation_year)} required /></label>
          <label className={LABEL}><span>{t('research.sotp.rate')}</span><Input name="discount_rate" inputMode="decimal" defaultValue={v(model?.discount_rate, 100)} required /></label>
          <label className={LABEL}><span>{t('research.sotp.sharesCurrent')}</span><Input name="shares_current" inputMode="decimal" defaultValue={v(model?.shares_current)} required /></label>
          <label className={LABEL}><span>{t('research.sotp.currency')}</span><Input name="currency" defaultValue={model?.currency ?? ''} placeholder={t('research.sotp.currencyPh')} /></label>
          <label className={LABEL}><span>{t('research.sotp.statedTotal')}</span><Input name="stated_value_per_share" inputMode="decimal" defaultValue={v(model?.stated_value_per_share)} /></label>
          <label className={`${LABEL} col-span-2`}><span>{t('research.sotp.sourceField')}</span><Input name="source" defaultValue={model?.source ?? ''} /></label>
          <input type="hidden" name="author" value={model?.author ?? ''} />
        </div>
        <fieldset className="grid gap-2"><legend className="text-sm font-semibold text-gray-200">{t('research.sotp.dilutionTitle')}</legend>
          {dilution.map((d, i) => (
            <div className="grid grid-cols-[1fr_7rem] gap-2" key={`dil-${i}`}>
              <Input aria-label={t('research.sotp.dilutionLabel')} name={`dil_label_${i}`} placeholder={t('research.sotp.dilutionLabel')} defaultValue={d?.label ?? ''} />
              <Input aria-label={t('research.sotp.dilutionShares')} name={`dil_shares_${i}`} inputMode="decimal" placeholder={t('research.sotp.dilutionShares')} defaultValue={v(d?.shares)} />
            </div>
          ))}
        </fieldset>
        <fieldset className="grid gap-3"><legend className="text-sm font-semibold text-gray-200">{t('research.sotp.partsTitle')}</legend>
          {parts.map((p, i) => (
            <div className="grid grid-cols-2 gap-2 rounded-md border border-gray-800 p-2 sm:grid-cols-4" key={`part-${i}`}>
              <label className={`${LABEL} col-span-2`}><span>{t('research.sotp.partName')}</span><Input name={`part_name_${i}`} defaultValue={p?.name ?? ''} /></label>
              <label className={LABEL}><span>{t('research.sotp.partKind')}</span>
                <select className="h-11 rounded-md border border-gray-800 bg-black px-2 text-base text-gray-200 sm:h-9 sm:text-sm" name={`part_kind_${i}`} defaultValue={p?.kind ?? 'operating'}>
                  <option value="operating">{t('research.sotp.kindOperating')}</option>
                  <option value="asset">{t('research.sotp.kindAsset')}</option>
                </select>
              </label>
              <label className={LABEL}><span>{t('research.sotp.partGroup')}</span><Input name={`part_group_${i}`} defaultValue={p?.group ?? ''} /></label>
              <label className={LABEL}><span>{t('research.sotp.revenue')}</span><Input name={`part_revenue_${i}`} inputMode="decimal" defaultValue={v(p?.revenue)} /></label>
              <label className={LABEL}><span>{t('research.sotp.ebitda')}</span><Input name={`part_ebitda_${i}`} inputMode="decimal" defaultValue={v(p?.ebitda)} /></label>
              <label className={LABEL}><span>{t('research.sotp.margin')}</span><Input name={`part_ebitda_margin_${i}`} inputMode="decimal" defaultValue={v(p?.ebitda_margin, 100)} /></label>
              <label className={LABEL}><span>{t('research.sotp.multiple')}</span><Input name={`part_multiple_${i}`} inputMode="decimal" defaultValue={v(p?.multiple)} /></label>
              <label className={LABEL}><span>{t('research.sotp.assetValue')}</span><Input name={`part_value_${i}`} inputMode="decimal" defaultValue={v(p?.value)} /></label>
              <label className={LABEL}><span>{t('research.sotp.probabilityField')}</span><Input name={`part_probability_${i}`} inputMode="decimal" defaultValue={v(p?.probability, 100)} /></label>
              <label className={LABEL}><span>{t('research.sotp.discounted')}</span>
                <select className="h-11 rounded-md border border-gray-800 bg-black px-2 text-base text-gray-200 sm:h-9 sm:text-sm" name={`part_discounted_${i}`} defaultValue={p?.discounted === false ? 'no' : 'yes'}>
                  <option value="yes">{t('research.sotp.discountedYes')}</option>
                  <option value="no">{t('research.sotp.discountedNo')}</option>
                </select>
              </label>
              <label className={`${LABEL} col-span-2 sm:col-span-4`}><span>{t('research.sotp.note')}</span><Input name={`part_note_${i}`} defaultValue={p?.note ?? ''} /></label>
            </div>
          ))}
        </fieldset>
        <fieldset className="grid gap-3"><legend className="text-sm font-semibold text-gray-200">{t('research.sotp.scenarios')}</legend>
          <p className="text-xs text-gray-500">{t('research.sotp.scenarioHint')}</p>
          {scenarios.map((s, i) => (
            <div className="grid grid-cols-2 gap-2 rounded-md border border-gray-800 p-2 sm:grid-cols-4" key={`sc-${i}`}>
              <input type="hidden" name={`sc_key_${i}`} value={s?.key ?? ''} />
              <label className={`${LABEL} col-span-2 sm:col-span-4`}><span>{t('research.sotp.scenarioLabel')}</span><Input name={`sc_label_${i}`} defaultValue={s?.label ?? ''} /></label>
              <label className={LABEL}><span>{t('research.sotp.revenueFactor')}</span><Input name={`sc_revenue_factor_${i}`} inputMode="decimal" defaultValue={v(s?.revenue_factor)} /></label>
              <label className={LABEL}><span>{t('research.sotp.multipleFactor')}</span><Input name={`sc_multiple_factor_${i}`} inputMode="decimal" defaultValue={v(s?.multiple_factor)} /></label>
              <label className={LABEL}><span>{t('research.sotp.delay')}</span><Input name={`sc_delay_years_${i}`} inputMode="decimal" defaultValue={v(s?.delay_years)} /></label>
              <label className={LABEL}><span>{t('research.sotp.rate')}</span><Input name={`sc_discount_rate_${i}`} inputMode="decimal" defaultValue={v(s?.discount_rate, 100)} /></label>
              <label className={LABEL}><span>{t('research.sotp.sharesTotal')}</span><Input name={`sc_shares_total_${i}`} inputMode="decimal" defaultValue={v(s?.shares_total)} /></label>
              <label className={LABEL}><span>{t('research.sotp.statedScenario')}</span><Input name={`sc_stated_value_per_share_${i}`} inputMode="decimal" defaultValue={v(s?.stated_value_per_share)} /></label>
              <label className={`${LABEL} col-span-2`}><span>{t('research.sotp.note')}</span><Input name={`sc_note_${i}`} defaultValue={s?.note ?? ''} /></label>
            </div>
          ))}
        </fieldset>
        <Button className="w-fit" type="submit">{t('research.sotp.save')}</Button>
      </MutationForm>
      {saved ? (
        <MutationForm action={deleteSotpResult.bind(null, ticker)} className="mt-3" successMessage={t('research.sotp.deleted')}>
          <Button className="w-fit" type="submit" variant="outline">{t('research.sotp.delete')}</Button>
        </MutationForm>
      ) : null}
    </details>
  );
}
