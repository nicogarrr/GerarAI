import Link from 'next/link';

import type { AstOrbitObject, AstOrbitOverview, AstsAnalysis } from '@/lib/actions/asts-orbits.actions';
import { formatNumber, formatUserDateTime } from '@/lib/format';
import { Panel } from '@/components/ui/panel';
import { AstSmaChart } from '@/components/research/AstSmaChart';

function SourceObjects({ objects }: { objects: AstOrbitObject[] }) {
  return <ul className="grid min-w-0 gap-3 lg:grid-cols-2">
    {objects.map((item) => <li className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4" key={item.norad_cat_id}>
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="break-words font-semibold text-gray-100">{item.object_name}</h3><span className="text-xs text-gray-500">NORAD {item.norad_cat_id}</span></div>
      <p className="mt-2 text-sm text-gray-300">Semieje mayor: {item.sma_km === null ? 'sin datos' : `${formatNumber(item.sma_km, { maximumFractionDigits: 1 })} km`}</p>
      <p className="mt-1 text-sm text-gray-300">Tendencia: {item.signal.delta_sma_km === null ? item.signal.status : `${item.signal.delta_sma_km > 0 ? '+' : ''}${formatNumber(item.signal.delta_sma_km, { maximumFractionDigits: 2 })} km en ${formatNumber(item.signal.hours, { maximumFractionDigits: 0 })} h`}</p>
      {item.signal.delta_sma_km !== null ? <p className="mt-1 text-sm text-amber-300">{item.signal.status}</p> : null}
      <p className="mt-2 text-xs text-gray-500">Época orbital: {formatUserDateTime(item.epoch)} · {item.history.length} observaciones guardadas</p>
      <AstSmaChart history={item.history} name={item.object_name} />
      <details className="mt-3"><summary className="min-h-11 cursor-pointer py-3 text-sm text-teal-300">Ver datos de cada época</summary><div className="max-h-52 overflow-auto rounded-md border border-gray-800 p-2 text-xs text-gray-300">{item.history.length ? item.history.map((sample) => <p className="flex flex-wrap justify-between gap-2 border-b border-gray-800 py-2 last:border-0" key={sample.epoch}><span>{formatUserDateTime(sample.epoch)}</span><span>{formatNumber(sample.sma_km, { maximumFractionDigits: 1 })} km</span></p>) : <p>Sin historial.</p>}</div></details>
    </li>)}
  </ul>;
}

function CatalogReading({ analysis }: { analysis: AstsAnalysis | null }) {
  const reading = analysis?.status === 'disponible' ? analysis.analysis : null;
  if (!analysis || !reading) {
    return <Panel title="Lectura del catálogo"><p className="text-sm text-gray-400">{analysis ? 'Sin datos frescos del catálogo.' : 'Lectura no disponible ahora. Recarga en unos segundos.'}</p></Panel>;
  }
  const interpretation = reading.llm_interpretation;
  return <Panel title="Lectura del catálogo">
    <p className="text-sm leading-6 text-gray-300">{reading.summary}</p>
    <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-300">
      {reading.observations.map((item) => <li key={item.text}>{item.text}</li>)}
    </ul>
    {interpretation ? <div className="mt-4 rounded-md border border-gray-800 p-3">
      <h3 className="text-sm font-semibold text-gray-100">Interpretación generativa, no verificada</h3>
      <p className="mt-2 text-sm leading-6 text-gray-300">{interpretation.summary}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-300">
        {interpretation.observations.map((item) => <li key={item.text}>{item.text}</li>)}
      </ul>
    </div> : null}
  </Panel>;
}

export function AstOrbitPanel({ data, analysis }: { data: AstOrbitOverview | null; analysis: AstsAnalysis | null }) {
  const supgp = data?.supgp;
  return <div className="space-y-5">
    <Panel title="Órbitas de la constelación AST" description="Semieje mayor estimado a partir de elementos orbitales públicos, no telemetría del satélite.">
      <p className="text-sm leading-6 text-gray-300">{data?.usage_note ?? 'La lectura orbital no está disponible ahora. No inferimos órbitas ni despliegues sin elementos vigentes.'}</p>
      <p className="mt-3 text-xs text-gray-500">Cadencia máxima de descarga: cada {data?.cadence_hours ?? 2} h. La época orbital de cada objeto se muestra aparte. GP y SupGP no se mezclan.</p>
    </Panel>
    <CatalogReading analysis={analysis} />
    <section className="space-y-3" aria-label="Historial GP">
      <h2 className="text-lg font-semibold text-gray-100">Catálogo GP · CelesTrak</h2>
      <p className="text-xs text-gray-400">Última descarga GP: {data?.fetched_at ? formatUserDateTime(data.fetched_at) : 'sin datos'}.</p>
      {data?.status === 'disponible' && data.objects.length ? <SourceObjects objects={data.objects} /> : <Panel title="Objetos GP"><p className="text-sm text-gray-400">Sin datos orbitales vigentes. El catálogo deja de publicarse tras 30 h sin una descarga válida.</p></Panel>}
    </section>
    <section className="space-y-3" aria-label="Historial SupGP">
      <h2 className="text-lg font-semibold text-gray-100">Elementos suplementarios SupGP · AST-E</h2>
      <p className="text-xs text-gray-400">Última descarga SupGP vigente: {supgp?.fetched_at ? formatUserDateTime(supgp.fetched_at) : 'sin datos'}. Fuente independiente de GP; no se comparan las series para emitir señales.</p>
      {supgp?.status === 'disponible' && supgp.objects.length ? <SourceObjects objects={supgp.objects} /> : <Panel title="Objetos SupGP"><p className="text-sm text-gray-400">Sin datos suplementarios vigentes. SupGP puede no estar disponible aunque GP sí lo esté.</p></Panel>}
    </section>
    <p className="text-xs leading-5 text-gray-500">Una firma compatible con variación orbital solo invita a revisar fuentes independientes. No confirma despliegue, maniobra ni posición actual.</p>
    <Link className="text-sm text-teal-300 hover:underline" href="/metodologia">Ver método y límites del cálculo</Link>
  </div>;
}
