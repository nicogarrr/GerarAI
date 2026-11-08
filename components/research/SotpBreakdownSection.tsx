import { Layers } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { deleteSotpResult, saveSotpResult } from '@/lib/actions/sotp.actions';
import { formatNumberForInput } from '@/lib/format';
import { getFormat, getLocale, getT } from '@/lib/i18n/server';
import { SOTP_EXTRA_DILUTION, SOTP_EXTRA_PARTS, SOTP_EXTRA_SCENARIOS, getSotp, type SotpModel, type SotpResponse } from '@/lib/research/sotp';

type T = Awaited<ReturnType<typeof getT>>;
type F = Awaited<ReturnType<typeof getFormat>>;

const SENS_KEYS = {
  multiples_minus_30: 'research.sotp.sens.multiplesMinus30',
  delay_2y: 'research.sotp.sens.delay2y',
  revenue_minus_50: 'research.sotp.sens.revenueMinus50',
  rate_plus_5pp: 'research.sotp.sens.ratePlus5pp',
  combined: 'research.sotp.sens.combined',
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
export async function SotpBreakdownSection({ ticker }: { ticker: string }) {
  const [data, t, fmt, locale] = await Promise.all([getSotp(ticker), getT(), getFormat(), getLocale()]);
  if (!data) return <p className={`${BOX} text-xs text-gray-400`} role="status">{t('research.sotp.loadError')}</p>;
  return <SotpBreakdownView data={data} t={t} fmt={fmt} locale={locale} ticker={ticker} />;
}

export function SotpBreakdownView({ data, t, fmt, locale, ticker }: { data: SotpResponse; t: T; fmt: F; locale: 'es' | 'en'; ticker: string }) {
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
        <span className="rounded-full border border-amber-700/60 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-200" data-testid="sotp-unvalidated">{t('research.sotp.unvalidated')}</span>
      </div>
      {data.origin === 'example' ? <p className="text-xs text-amber-200/90">{t('research.sotp.exampleDraft', { author: model?.author ?? '—' })}</p> : null}
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
                      </span>
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
      <SotpEditor model={model} t={t} locale={locale} ticker={ticker} saved={data.origin === 'saved'} versions={data.saved?.versions ?? 0} />
    </section>
  );
}

function SotpEditor({ model, t, locale, ticker, saved, versions }: { model?: SotpModel; t: T; locale: 'es' | 'en'; ticker: string; saved: boolean; versions: number }) {
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
