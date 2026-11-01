import { GitCompare, Plus } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { createDriverAssumptionResult, getDriverAssumptions } from '@/lib/actions/research-tools.actions';
import { formatConfidence, formatDate, formatNumber, naFor } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

export type DriverAssumptions = Awaited<ReturnType<typeof getDriverAssumptions>>;

/** Escenarios bear/base/bull -> clave de texto (es/en). */
const STATUS_KEYS = {
  bear: 'research.driverSection.scenarioBear',
  base: 'research.driverSection.scenarioBase',
  bull: 'research.driverSection.scenarioBull',
} as const;

function label(value: string | null | undefined, t: TranslateFn): string {
  if (!value) return '—';
  return Object.hasOwn(STATUS_KEYS, value) ? t(STATUS_KEYS[value as keyof typeof STATUS_KEYS]) : value.replaceAll('_', ' ');
}

/**
 * Supuestos de drivers como sección de la pestaña Valoración (antes página
 * propia `/driver-assumptions`, que ahora redirige aquí). Misma tabla de
 * escenario activo, mismo historial y mismo formulario de nueva versión.
 */
export function DriverAssumptionsSection({ ticker, assumptions, locale = 'es' }: { ticker: string; assumptions: DriverAssumptions; locale?: Locale }) {
  const t = createTranslator(locale);
  const latest = new Map<string, DriverAssumptions[number]>();
  for (const item of assumptions) latest.set(`${item.driver_key}:${item.fiscal_year}:${item.scenario}`, item);
  const current = [...latest.values()].sort((a, b) => a.driver_key.localeCompare(b.driver_key) || a.fiscal_year - b.fiscal_year || a.scenario.localeCompare(b.scenario));
  return <div className="grid min-w-0 gap-6">
    <MutationForm action={createDriverAssumptionResult.bind(null, ticker)} className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage={t('research.driverSection.created')}>
<div className="mb-4 flex items-center gap-2"><Plus aria-hidden="true" className="h-5 w-5 text-teal-300" /><h3 className="font-semibold text-gray-100">{t('research.driverSection.newVersion')}</h3></div><div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.driverSection.driverKey')}</span><Input list="driver-keys" name="driver_key" placeholder={t('research.driverSection.driverKey')} required /></label><datalist id="driver-keys">{[...new Set(assumptions.map((item) => item.driver_key))].map((key) => <option key={key} value={key} />)}</datalist><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.driverSection.fiscalYear')}</span><Input min="1900" max="2200" name="fiscal_year" placeholder={t('research.driverSection.fiscalYear')} required type="number" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.driverSection.scenario')}</span><select className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:h-9 sm:text-sm" name="scenario" defaultValue="base"><option value="bear">{t('research.driverSection.bear')}</option><option value="base">Base</option><option value="bull">{t('research.driverSection.bull')}</option></select></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.driverSection.value')}</span><Input name="value" placeholder={t('research.driverSection.value')} required type="text" inputMode="decimal" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.driverSection.confidence01')}</span><Input name="confidence" defaultValue="1" required type="text" inputMode="decimal" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>{t('research.driverSection.sourceOrAdjustment')}</span><Input name="source" placeholder={t('research.driverSection.sourceOrAdjustment')} required /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 col-span-full"><span>{t('research.driverSection.rationale')}</span><Textarea name="rationale" placeholder={t('research.driverSection.rationalePh')} required /></label><Button className="w-fit" type="submit"><Plus aria-hidden="true" className="h-4 w-4" />{t('research.driverSection.createVersion')}</Button></div></MutationForm>
    <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="mb-4 flex items-center gap-2"><GitCompare aria-hidden="true" className="h-5 w-5 text-teal-300" /><h3 className="text-lg font-semibold text-gray-100">{t('research.driverSection.activeTable')}</h3></div>
{current.length ? <OverflowScrollRegion label={t('research.driverSection.activeTable')}><table className="w-full min-w-[640px] sm:min-w-[1050px] text-left text-sm"><caption className="sr-only">{t('research.driverSection.caption')}</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2" scope="col">{t('research.driverSection.variable')}</th><th className="border-b border-gray-800 py-2" scope="col">{t('research.driverSection.year')}</th><th className="border-b border-gray-800 py-2" scope="col">{t('research.driverSection.scenario')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{t('research.driverSection.value')}</th><th className="border-b border-gray-800 py-2" scope="col">{t('research.driverSection.source')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{t('research.driverSection.confidence')}</th><th className="border-b border-gray-800 py-2" scope="col">{t('research.driverSection.rationale')}</th><th className="border-b border-gray-800 py-2" scope="col">{t('research.driverSection.version')}</th></tr></thead><tbody>{current.map((item) => <tr className="border-b border-gray-900" key={`${item.driver_key}-${item.fiscal_year}-${item.scenario}`}><th className="py-3 text-left text-sm font-semibold text-gray-200" scope="row">{item.driver_key}</th><td className="py-3 text-gray-300">{item.fiscal_year}</td><td className="py-3"><Badge className={item.scenario === 'bear' ? 'border-red-900 text-red-300' : item.scenario === 'bull' ? 'border-teal-800 text-teal-300' : ''} variant="outline">{label(item.scenario, t)}</Badge></td><td className="py-3 text-right text-gray-100">{formatNumber(item.value, {}, undefined, locale)}</td><td className="py-3 text-gray-400">{item.source}</td><td className="py-3 text-right text-gray-400">{formatConfidence(item.confidence, naFor(locale))}</td><td className="max-w-sm py-3 text-gray-400">{item.rationale}</td><td className="py-3 text-xs text-gray-500">#{item.id}{item.previous_version_id ? ` ← #${item.previous_version_id}` : ''}</td></tr>)}</tbody></table></OverflowScrollRegion> : <div aria-label={t('research.driverSection.activeTable')} className="overflow-x-auto" role="region" tabIndex={0}><table className="w-full min-w-[640px] sm:min-w-[1050px] text-left text-sm"><tbody><tr><td className="py-5 text-gray-500" colSpan={8}>{t('research.driverSection.empty')}</td></tr></tbody></table></div>}</section>
    <details className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5"><summary className="cursor-pointer py-2.5 font-semibold text-gray-200 sm:py-0">{t('research.driverSection.history', { count: assumptions.length })}</summary>
<div className="mt-4 grid gap-2">{assumptions.slice().reverse().map((item) => <div className="grid gap-1.5 rounded-lg border border-gray-800 p-3 text-sm sm:grid-cols-2 md:grid-cols-[1fr_90px_90px_120px_1fr]" key={item.id}><span className="text-gray-200">{item.driver_key}</span><span>{item.fiscal_year}</span><span>{label(item.scenario, t)}</span><span>{formatNumber(item.value, {}, undefined, locale)}</span><span className="text-gray-500">v#{item.id} · {formatDate(item.created_at, undefined, undefined, locale)}</span></div>)}</div></details>
  </div>;
}
