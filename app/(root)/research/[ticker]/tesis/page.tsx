import { canShowThesisText, WithheldThesisText } from '@/components/research/ThesisSummary';
import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft, FileDown, FileText } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { formatGeneratedDate, formatPercent, formatUserDate } from '@/lib/format';
import {
  getResearchCompanySnapshot,
  getResearchThesisWorkspace,
} from '@/lib/actions/research.actions';
import { thesisMoney } from '@/lib/research/thesis-number-format';
import { cleanThesisText } from '@/lib/research/thesis-text';
import { isValidCurrencyCode } from '@/lib/format';
import PrintButton from '@/components/research/PrintButton';
import { PROVENANCE_GROUPS, provenanceBasisEs, provenanceGroup } from '@/lib/research/provenance-groups';
import { isVerifiedOficial, provenanceUrls } from '@/lib/research/provenance-item';
import { capitalizeLabel, formatProvenanceValue } from '@/lib/research/provenance-format';
import { metricLabel } from '@/lib/research/metric-labels';
import { publicEditorial } from '@/lib/public-fonts';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Tesis de inversión',
  description: 'Documento de lectura de la tesis publicada, con cifras, procedencia y márgenes.',
};

type PageProps = { params: Promise<{ ticker: string }> };

const STATUS_LABELS: Record<string, string> = {
  draft: 'borrador',
  draft_failed_audit: 'borrador (auditoría no superada)',
  review: 'en revisión',
  approved: 'aprobada',
  published: 'publicada',
  rejected: 'rechazada',
  stale: 'desactualizada',
  superseded: 'sustituida',
  insufficient_data: 'datos insuficientes',
};

function statusLabel(status: string | null | undefined): string {
  if (!status) return 'desconocido';
  return STATUS_LABELS[status] ?? 'desconocido';
}

const RATING_LABELS: Record<string, string> = {
  buy: 'compra', accumulate: 'acumular', overweight: 'sobreponderar',
  hold: 'mantener', underweight: 'infraponderar', trim: 'recortar',
  sell: 'venta', avoid: 'evitar', watch: 'seguimiento',
  attractive: 'atractiva', expensive: 'cara',
  incomplete_price: 'precio incompleto', blocked: 'bloqueada',
  insufficient_data: 'datos insuficientes',
};

function money(value: string | null, currency: string | null | undefined): string {
  if (value === null) return 'N/D';
  const parsed = Number(value);
  if (Number.isNaN(parsed) || !isValidCurrencyCode(currency)) return 'N/D';
  return thesisMoney(parsed, currency);
}

/**
 * Vista de lectura de la tesis PUBLICADA: documento limpio, imprimible y
 * descargable (PDF/Markdown). Solo lo que contiene la version publicada;
 * un borrador mas reciente se anuncia sin cifras ni margen (regla vigente).
 */
export default async function ThesisReadingPage({ params }: PageProps) {
  const { ticker: rawTicker } = await params;
  const ticker = rawTicker.toUpperCase();

  const [snapshot, workspace] = await Promise.all([
    getResearchCompanySnapshot(ticker).catch(() => null),
    getResearchThesisWorkspace(ticker).catch(() => null),
  ]);
  const company = snapshot?.company ?? null;
  const currency = company?.currency ?? null;
  const latest = workspace?.thesis ?? null;
  const published = workspace ? await readLatestPublished(ticker) : null;
  // Fuentes por cifra: /versions no las trae; /latest si. Solo se muestran
  // cuando la publicada ES la ultima version: la procedencia de un borrador
  // mas nuevo no describe este documento y afirmarlo seria inventarlo.
  const provenance =
    published && latest && latest.id === published.id
      ? (latest.inputs_provenance ?? null)
      : null;

  const encoded = encodeURIComponent(ticker);
  const name = company?.name ?? ticker;
  const generated = published ? formatGeneratedDate(published.created_at) : null;
  // El precio persistido con la versión es el que usó el MODELO al generarla
  // (snapshot de posición o último cierre), no la cotización de hoy: nunca
  // se rotula "Precio actual". La fecha de la cotización solo se muestra si
  // el motor la persistió en valuation_basis; si no, sin fecha (no se inventa).
  const priceAsOf = published?.valuation_basis?.price_as_of ?? null;
  const modelPriceLabel = priceAsOf
    ? `Precio del modelo al ${formatUserDate(priceAsOf)}`
    : 'Precio del modelo';
  // La columna Probabilidad solo se muestra cuando el motor persistio
  // probabilidades: sin ellas seria un «N/D» triple que aparenta un dato
  // que no existe (regla de veracidad: no inventar ni insinuar datos).
  const hasProbabilities = published
    ? [published.scenario_probabilities?.bear,
       published.scenario_probabilities?.base,
       published.scenario_probabilities?.bull].some((p) => typeof p === 'number')
    : false;
  // Sin valores de escenario (p. ej. insufficient_data) la tabla no se
  // pinta: serian tres filas de «N/D» aparentando una valoracion que el
  // modelo no produjo. Las probabilidades pueden existir aun sin valores
  // (el motor las persiste aparte), pero sin valores no hay tabla que
  // acompanar: se dice tal cual.
  const hasScenarioValues = published
    ? [published.bear_value, published.base_value, published.bull_value].some((v) => v !== null)
    : false;

  // Retain all persisted free text and numeric values together. A missing
  // snapshot is not evidence of publishability, even for a published archive.
  const displayedVersion = published ?? latest;
  if (displayedVersion && !canShowThesisText(displayedVersion, snapshot?.model_summary)) {
    return (
      <main id="content" className={`print-document min-h-screen bg-surface-0 px-4 py-6 text-gray-100 sm:px-6 lg:px-8 ${publicEditorial.variable}`}>
        <div className="mx-auto max-w-3xl">
          <Link href={`/research/${encoded}?view=thesis`} className="text-sm text-teal-300 underline">Ficha de {ticker}</Link>
          <h1 className="mt-8 text-3xl text-gray-50">{ticker} · {name}</h1>
          <WithheldThesisText thesis={displayedVersion} model={snapshot?.model_summary} />
          <p className="mt-4 text-sm leading-6 text-gray-400">Sin valoración ni texto de inversión verificables para esta vista. Revisa las fuentes y los datos pendientes en la ficha antes de publicar una nueva versión.</p>
        </div>
      </main>
    );
  }

  return (
    <main id="content" className={`print-document min-h-screen bg-surface-0 px-4 py-6 text-gray-100 sm:px-6 lg:px-8 ${publicEditorial.variable}`}>
      <div className="mx-auto max-w-3xl">
        <div className="print:hidden flex flex-wrap items-center gap-3">
          <Link
            href={`/research/${encoded}?view=thesis`}
            className="inline-flex min-h-[44px] items-center text-sm text-gray-500 hover:text-gray-200 sm:min-h-0"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />Ficha de {ticker}
          </Link>
          {published ? (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <PrintButton />
            <a
              href={`/api/thesis/${encoded}/pdf`}
              download
              className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-teal-700 hover:text-teal-200 sm:min-h-0"
            >
              <FileDown className="h-4 w-4" />PDF
            </a>
            <a
              href={`/api/thesis-memo/${encoded}`}
              download
              className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-teal-700 hover:text-teal-200 sm:min-h-0"
            >
              <FileText className="h-4 w-4" />Markdown
            </a>
          </div>
          ) : null}
        </div>

        {!published && latest && latest.status === 'insufficient_data' ? (
          <article className="mt-8 min-w-0 max-w-full space-y-8 [overflow-wrap:anywhere]">
            <header className="border-b border-gray-800 pb-6">
              <p className="text-xs uppercase tracking-wide text-gray-500">Tesis de inversión</p>
              <h1 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="mt-2 text-3xl text-gray-50 sm:text-4xl">
                {ticker} · {name}
              </h1>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge variant="outline">PROVISIONAL — no publicada</Badge>
                <Badge variant="outline">{statusLabel(latest.status)}</Badge>
                <Badge variant="outline">v{latest.version}</Badge>
                {latest.created_at ? <span className="text-xs text-gray-500">generada el {formatGeneratedDate(latest.created_at)}</span> : null}
              </div>
              <p role="status" className="mt-4 rounded-lg border border-amber-800/60 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
                Documento provisional generado con la evidencia disponible: no es una versión
                publicada. El modelo no produjo una valoración calculable (la causa exacta está
                declarada en el memo, secciones 13 y 21): esta vista no contiene cifras de
                valoración porque no existen, no porque se oculten.
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <PrintButton />
                <a
                  href={`/api/thesis/${encoded}/pdf?draft=1`}
                  download
                  className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-teal-700 hover:text-teal-200 sm:min-h-0"
                >
                  <FileDown className="h-4 w-4" />Ficha del borrador (PDF, v{latest.version})
                </a>
                <span className="text-xs text-gray-500">
                  El PDF solo lleva la ficha del borrador (lista blanca del backend); el documento completo es esta página.
                </span>
                <EmptyLink href={`/research/${encoded}?view=thesis`}>Revisar la v{latest.version} en la ficha</EmptyLink>
              </div>
            </header>

            {latest.executive_summary ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Resumen ejecutivo</h2>
                <p className="mt-3 text-base leading-8 text-gray-200">{cleanThesisText(latest.executive_summary)}</p>
              </section>
            ) : null}

            {latest.hypothesis ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Hipótesis</h2>
                <p className="mt-3 text-base leading-8 text-gray-200">{cleanThesisText(latest.hypothesis)}</p>
              </section>
            ) : null}

            <section>
              <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Escenarios y valoración</h2>
              <p className="mt-4 text-sm text-gray-400">
                Sin cifras de valoración en esta vista: el modelo no produjo una valoración
                calculable con los datos disponibles; la causa exacta está declarada en el memo
                (sección 13) y los datos pendientes en la sección 21.
              </p>
            </section>

            {(latest.narrative_sections ?? []).map((section) => (
              <section key={section.titulo}>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">{section.titulo}</h2>
                {section.parrafos.map((parrafo, index) => (
                  <p key={index} className="mt-3 text-base leading-8 text-gray-200">{cleanThesisText(parrafo)}</p>
                ))}
              </section>
            ))}

            {(latest.catalysts ?? []).length > 0 ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Catalizadores</h2>
                <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-gray-200">
                  {(latest.catalysts ?? []).map((catalyst, index) => (
                    <li key={index}>
                      {catalyst.label ?? 'Catalizador'}{catalyst.date ? ` (${formatUserDate(catalyst.date)})` : ''}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {(latest.invalidation_criteria ?? []).length > 0 ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Qué invalidaría la tesis</h2>
                <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-gray-200">
                  {(latest.invalidation_criteria ?? []).map((criterion, index) => (
                    <li key={index}>{criterion}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            <footer className="border-t border-gray-800 pt-4 text-xs leading-6 text-gray-500">
              <p>
                Puntuaciones del pipeline sobre este borrador (no son una medida de la calidad o
                completitud de la tesis): confianza de datos {latest.data_confidence_score}/100 ·
                cobertura de fuentes {latest.source_coverage_score}/100 · red-team {latest.red_team_score}/100.
              </p>
              <p className="mt-2">
                Documento informativo de investigación, provisional y no publicado. No es asesoramiento financiero ni recomendación de compra o venta.
              </p>
            </footer>
          </article>
        ) : !published ? (
          <div className="mt-10">
            <EmptyState
              action={latest ? <EmptyLink href={`/research/${encoded}?view=thesis`}>Revisar la v{latest.version} en la ficha</EmptyLink> : <EmptyLink href={`/research/${encoded}`}>Generar la primera tesis desde la ficha</EmptyLink>}
              description={latest ? `La v${latest.version} está en estado «${statusLabel(latest.status)}»: solo se enseñan las cifras y el margen de una versión publicada.` : `Todavía no se ha generado ninguna tesis de ${ticker}. Puedes generar la primera desde su ficha.`}
              title={`Aún no hay ninguna tesis publicada de ${ticker}.`}
              titleAs="h1"
            />
          </div>
        ) : (
          <article className="mt-8 min-w-0 max-w-full space-y-8 [overflow-wrap:anywhere]">
            <header className="border-b border-gray-800 pb-6">
              <p className="text-xs uppercase tracking-wide text-gray-500">Tesis de inversión</p>
              <h1 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="mt-2 text-3xl text-gray-50 sm:text-4xl">
                {ticker} · {name}
              </h1>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge>{RATING_LABELS[published.rating] ?? published.rating}</Badge>
                <Badge variant="outline">v{published.version}</Badge>
                {generated ? <span className="text-xs text-gray-500">generada el {generated}</span> : null}
              </div>
              {latest && latest.version !== published.version ? (
                <p className="mt-3 text-xs text-amber-300">
                  Existe una v{latest.version} en borrador pendiente de aprobación; sus cifras no se muestran hasta publicarse.
                </p>
              ) : null}
            </header>

            {published.executive_summary ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Resumen ejecutivo</h2>
                <p className="mt-3 text-base leading-8 text-gray-200">{cleanThesisText(published.executive_summary)}</p>
              </section>
            ) : null}

            {published.hypothesis ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Hipótesis</h2>
                <p className="mt-3 text-base leading-8 text-gray-200">{cleanThesisText(published.hypothesis)}</p>
              </section>
            ) : null}

            <section>
              <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Escenarios y valoración</h2>
              {hasScenarioValues ? (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700 text-left text-xs uppercase text-gray-500">
                      <th className="py-2 pr-4">Escenario</th>
                      <th className="py-2 pr-4">Valor</th>
                      {hasProbabilities ? <th className="py-2">Probabilidad</th> : null}
                    </tr>
                  </thead>
                  <tbody className="text-gray-200">
                    {([
                      ['Bajista', published.bear_value, published.scenario_probabilities?.bear],
                      ['Base', published.base_value, published.scenario_probabilities?.base],
                      ['Alcista', published.bull_value, published.scenario_probabilities?.bull],
                    ] as const).map(([label, value, probability]) => (
                      <tr key={label} className="border-b border-gray-800/70">
                        <td className="py-2 pr-4 text-gray-400">{label}</td>
                        <td className="py-2 pr-4 font-medium">{money(value, currency)}</td>
                        {hasProbabilities ? (
                          <td className="py-2">{typeof probability === 'number' ? formatPercent(probability, { digits: 0 }) : 'N/D'}</td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              ) : (
                <p className="mt-4 text-sm text-gray-400">Sin cifras de valoración.</p>
              )}
              <p className="mt-3 text-sm text-gray-400">
                {modelPriceLabel}: {money(published.current_price, currency)} · Valor esperado: {money(published.expected_value, currency)}
                {published.margin_of_safety !== null
                  ? ` · Margen de seguridad: ${formatPercent(Number(published.margin_of_safety))}`
                  : ''}
              </p>
            </section>

            {provenance && provenance.length > 0 ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Procedencia de las cifras</h2>
                <div className="mt-4 space-y-4">
                  {PROVENANCE_GROUPS.map((group) => {
                    const rows = provenance.filter(
                      (item) => provenanceGroup(item.label as string | undefined, isVerifiedOficial(item)) === group.key,
                    );
                    if (rows.length === 0) return null;
                    return (
                      <div key={group.key}>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{group.title}</h3>
                        <dl className="mt-1 divide-y divide-gray-800/70">
                          {rows.map((item) => {
                            const urls = provenanceUrls(item);
                            const basis = provenanceBasisEs(item.base_inferencia ?? item.method);
                            return (
                              <div key={item.key} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2 text-sm">
                                <dt className="text-gray-300">{capitalizeLabel(metricLabel(item.key))}</dt>
                                <dd className="ml-auto font-medium tabular-nums text-gray-100">{formatProvenanceValue(item.value, item.unit)}</dd>
                                <dd className="basis-full text-xs text-gray-500">
                                  {basis ?? 'Base no documentada'}
                                  {urls.map((url, index) => (
                                    <a
                                      key={url}
                                      href={url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      aria-label={`Fuente ${index + 1}`}
                                      className="ml-1 text-teal-400 underline print:text-gray-700 print:no-underline"
                                    >
                                      [{index + 1}]
                                    </a>
                                  ))}
                                </dd>
                              </div>
                            );
                          })}
                        </dl>
                      </div>
                    );
                  })}
                </div>
              </section>
            ) : null}

            {(published.narrative_sections ?? []).map((section) => (
              <section key={section.titulo}>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">{section.titulo}</h2>
                {section.parrafos.map((parrafo, index) => (
                  <p key={index} className="mt-3 text-base leading-8 text-gray-200">{cleanThesisText(parrafo)}</p>
                ))}
              </section>
            ))}

            {(published.catalysts ?? []).length > 0 ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Catalizadores</h2>
                <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-gray-200">
                  {(published.catalysts ?? []).map((catalyst, index) => (
                    <li key={index}>
                      {catalyst.label ?? 'Catalizador'}{catalyst.date ? ` (${formatUserDate(catalyst.date)})` : ''}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {(published.invalidation_criteria ?? []).length > 0 ? (
              <section>
                <h2 style={{ fontFamily: "var(--font-editorial), Georgia, serif" }} className="text-xl text-teal-300">Qué invalidaría la tesis</h2>
                <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-gray-200">
                  {(published.invalidation_criteria ?? []).map((criterion, index) => (
                    <li key={index}>{criterion}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            <footer className="border-t border-gray-800 pt-4 text-xs leading-6 text-gray-500">
              <p>
                Calidad de la evidencia: confianza de datos {published.data_confidence_score}/100 ·
                cobertura de fuentes {published.source_coverage_score}/100 · red-team {published.red_team_score}/100.
              </p>
              <p className="mt-2">
                Documento informativo de investigación. No es asesoramiento financiero ni recomendación de compra o venta.
              </p>
            </footer>
          </article>
        )}
      </div>
    </main>
  );
}

/** La publicada con contenido completo: /versions trae cada version entera. */
async function readLatestPublished(ticker: string) {
  const { researchRequest } = await import('@/lib/research/client');
  type Version = NonNullable<Awaited<ReturnType<typeof getResearchThesisWorkspace>>['thesis']>;
  let versions: Version[] = [];
  try {
    versions = await researchRequest<Version[]>(
      `/api/thesis/${encodeURIComponent(ticker)}/versions`,
      { timeoutMs: 12_000 },
    );
  } catch {
    versions = [];
  }
  const published = versions
    .filter((version) => version.status === 'published')
    .sort((a, b) => b.version - a.version)[0];
  return published ?? null;
}
