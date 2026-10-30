import { GitCompare, Plus } from 'lucide-react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { createDriverAssumption, getDriverAssumptions } from '@/lib/actions/research-tools.actions';
import { formatConfidence, formatDate, formatNumber } from '@/lib/format';

export type DriverAssumptions = Awaited<ReturnType<typeof getDriverAssumptions>>;

/** Etiquetas en español para los escenarios bear/base/bull */
const STATUS_LABELS: Record<string, string> = {
  bear: 'bajista',
  base: 'base',
  bull: 'alcista',
};

function label(value: string | null | undefined): string {
  if (!value) return '—';
  return STATUS_LABELS[value] ?? value.replaceAll('_', ' ');
}

/**
 * Supuestos de drivers como sección de la pestaña Valoración (antes página
 * propia `/driver-assumptions`, que ahora redirige aquí). Misma tabla de
 * escenario activo, mismo historial y mismo formulario de nueva versión.
 */
export function DriverAssumptionsSection({ ticker, assumptions }: { ticker: string; assumptions: DriverAssumptions }) {
  const latest = new Map<string, DriverAssumptions[number]>();
  for (const item of assumptions) latest.set(`${item.driver_key}:${item.fiscal_year}:${item.scenario}`, item);
  const current = [...latest.values()].sort((a, b) => a.driver_key.localeCompare(b.driver_key) || a.fiscal_year - b.fiscal_year || a.scenario.localeCompare(b.scenario));
  return <div className="grid min-w-0 gap-6">
    <MutationForm action={createDriverAssumption.bind(null, ticker)} className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5" resetOnSuccess successMessage="Versión de supuestos creada">
<div className="mb-4 flex items-center gap-2"><Plus aria-hidden="true" className="h-5 w-5 text-teal-300" /><h3 className="font-semibold text-gray-100">Nueva versión de supuestos</h3></div><div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Clave del driver</span><Input list="driver-keys" name="driver_key" placeholder="Clave del driver" required /></label><datalist id="driver-keys">{[...new Set(assumptions.map((item) => item.driver_key))].map((key) => <option key={key} value={key} />)}</datalist><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Año fiscal</span><Input min="1900" max="2200" name="fiscal_year" placeholder="Año fiscal" required type="number" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Escenario</span><select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200" name="scenario" defaultValue="base"><option value="bear">Bajista</option><option value="base">Base</option><option value="bull">Alcista</option></select></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Valor</span><Input name="value" placeholder="Valor" required type="text" inputMode="decimal" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Confianza (0-1)</span><Input name="confidence" defaultValue="1" required type="text" inputMode="decimal" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Fuente o ajuste del analista</span><Input name="source" placeholder="Fuente o ajuste del analista" required /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400 col-span-full"><span>Justificación</span><Textarea name="rationale" placeholder="Por qué es adecuada esta suposición" required /></label><Button className="w-fit" type="submit"><Plus aria-hidden="true" className="h-4 w-4" />Crear versión</Button></div></MutationForm>
    <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="mb-4 flex items-center gap-2"><GitCompare aria-hidden="true" className="h-5 w-5 text-teal-300" /><h3 className="text-lg font-semibold text-gray-100">Tabla de escenario activo</h3></div>
{current.length ? <OverflowScrollRegion label="Tabla de escenario activo"><table className="w-full min-w-[640px] sm:min-w-[1050px] text-left text-sm"><caption className="sr-only">Supuestos activos por variable, año fiscal y escenario, con valor, fuente, confianza, justificación y versión</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2" scope="col">Variable</th><th className="border-b border-gray-800 py-2" scope="col">Año</th><th className="border-b border-gray-800 py-2" scope="col">Escenario</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Valor</th><th className="border-b border-gray-800 py-2" scope="col">Fuente</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Confianza</th><th className="border-b border-gray-800 py-2" scope="col">Justificación</th><th className="border-b border-gray-800 py-2" scope="col">Versión</th></tr></thead><tbody>{current.map((item) => <tr className="border-b border-gray-900" key={`${item.driver_key}-${item.fiscal_year}-${item.scenario}`}><th className="py-3 text-left text-sm font-semibold text-gray-200" scope="row">{item.driver_key}</th><td className="py-3 text-gray-300">{item.fiscal_year}</td><td className="py-3"><Badge className={item.scenario === 'bear' ? 'border-red-900 text-red-300' : item.scenario === 'bull' ? 'border-teal-800 text-teal-300' : ''} variant="outline">{label(item.scenario)}</Badge></td><td className="py-3 text-right text-gray-100">{formatNumber(item.value)}</td><td className="py-3 text-gray-400">{item.source}</td><td className="py-3 text-right text-gray-400">{formatConfidence(item.confidence)}</td><td className="max-w-sm py-3 text-gray-400">{item.rationale}</td><td className="py-3 text-xs text-gray-500">#{item.id}{item.previous_version_id ? ` ← #${item.previous_version_id}` : ''}</td></tr>)}</tbody></table></OverflowScrollRegion> : <div aria-label="Tabla de escenario activo" className="overflow-x-auto" role="region" tabIndex={0}><table className="w-full min-w-[640px] sm:min-w-[1050px] text-left text-sm"><tbody><tr><td className="py-5 text-gray-500" colSpan={8}>Construye primero el modelo a largo plazo y luego crea aquí los ajustes de drivers.</td></tr></tbody></table></div>}</section>
    <details className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-5"><summary className="cursor-pointer py-2.5 font-semibold text-gray-200 sm:py-0">Historial de versiones ({assumptions.length})</summary>
<div className="mt-4 grid gap-2">{assumptions.slice().reverse().map((item) => <div className="grid gap-1.5 rounded-lg border border-gray-800 p-3 text-sm sm:grid-cols-2 md:grid-cols-[1fr_90px_90px_120px_1fr]" key={item.id}><span className="text-gray-200">{item.driver_key}</span><span>{item.fiscal_year}</span><span>{label(item.scenario)}</span><span>{formatNumber(item.value)}</span><span className="text-gray-500">v#{item.id} · {formatDate(item.created_at)}</span></div>)}</div></details>
  </div>;
}
