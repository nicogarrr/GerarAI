import { frameworkTerm } from '@/lib/research/framework-terms';
import { thesisMoney, thesisEps } from '@/lib/research/thesis-number-format';
import { thesisScenarioDisplay } from '@/lib/research/listed-share-values';
import { formatGeneratedDate, formatPercent, isValidCurrencyCode, marginOfSafetyDisplay, NA } from '@/lib/format';
import { capitalizeLabel, formatProvenanceValue } from '@/lib/research/provenance-format';
import { metricLabel } from '@/lib/research/metric-labels';
import { cleanThesisText } from '@/lib/research/thesis-text';
import { GlossaryTerm } from '@/components/GlossaryTerm';
import ScenarioAssumptions from '@/components/research/ScenarioAssumptions';
import ThesisHumanInputForm from '@/components/research/ThesisHumanInputForm';
import ThesisDebatePanel from '@/components/research/ThesisDebatePanel';
import ThesisAudioPlayer from '@/components/research/ThesisAudioPlayer';
import ThesisMarkdown from '@/components/research/ThesisMarkdown';
import { Badge } from '@/components/ui/badge';
import type { ResearchThesis } from '@/lib/actions/research.actions';
import type { GlossaryKey } from '@/lib/glossary';

/** Etiquetas en español para los enums persistidos por el backend (mismo
 *  vocabulario que la ficha y el indice de research). */
const RATING_LABELS: Record<string, string> = {
  buy: 'compra',
  accumulate: 'acumular',
  overweight: 'sobreponderar',
  hold: 'mantener',
  underweight: 'infraponderar',
  trim: 'recortar',
  sell: 'venta',
  avoid: 'evitar',
  watch: 'seguimiento',
  attractive: 'atractiva',
  expensive: 'cara',
  incomplete_price: 'precio incompleto',
  blocked: 'bloqueada',
  insufficient_data: 'datos insuficientes',
};

const STATUS_LABELS: Record<string, string> = {
  draft: 'borrador',
  review: 'en revisión',
  approved: 'aprobada',
  published: 'publicada',
  rejected: 'rechazada',
  stale: 'desactualizada',
  draft_failed_audit: 'borrador (auditoría no superada)',
};

function enumLabel(map: Record<string, string>, value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NA;
  return map[value] ?? value.replaceAll('_', ' ');
}

type ProvenanceItem = NonNullable<ResearchThesis['inputs_provenance']>[number];

/** Fail-closed: solo es OFICIAL lo que llega marcado OFICIAL con TODAS sus
 *  fuentes oficiales, https y con fecha. Todo lo demás (payload legacy, sin
 *  origen, etiquetas derivado/supuesto/estimación) se muestra como INFERIDO. */
function isVerifiedOficial(item: ProvenanceItem): boolean {
  const fuentes = item.fuentes ?? [];
  return (
    item.origen === 'OFICIAL' &&
    fuentes.length > 0 &&
    fuentes.every((f) => f.oficial && !!f.fecha && !!f.url && /^https:\/\//.test(f.url))
  );
}

/**
 * Importes de la tesis en la divisa del LISTADO (la misma que usa
 * ValuationView). Antes esta función fijaba el dólar: /research/ASML.AS pintaba
 * los mismos 1.522,60 como «US$» en la tesis y como «€» en la valoración. Sin
 * divisa válida el importe NO se pinta: NA, nunca una moneda inventada.
 */
function money(
  value: number | string | null | undefined,
  currency: string | null | undefined,
): string {
  const parsed = typeof value === 'string' ? Number(value) : value;
  if (parsed === null || parsed === undefined || Number.isNaN(parsed)) return NA;
  if (!isValidCurrencyCode(currency)) return NA;
  return thesisMoney(parsed, currency);
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const clamped = Math.max(0, Math.min(100, value));
  const tone =
    clamped >= 70 ? 'bg-teal-400' : clamped >= 40 ? 'bg-amber-400' : 'bg-red-400';
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="truncate text-gray-400">{label}</span>
        <span className="font-mono text-gray-300">{clamped}/100</span>
      </div>
      <div className="mt-1 h-1.5 w-full rounded-full bg-gray-800">
        <div className={`h-1.5 rounded-full ${tone}`} style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

function ScenarioCell({
  label,
  value,
  currency,
  probability,
  highlight = false,
  glossaryKey,
}: {
  label: string;
  value: number | string | null | undefined;
  currency: string | null | undefined;
  probability?: number | null;
  highlight?: boolean;
  glossaryKey?: GlossaryKey;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        highlight ? 'border-teal-800 bg-teal-950/20' : 'border-gray-800 bg-black/20'
      }`}
    >
      <div className="text-xs uppercase text-gray-500">
        {glossaryKey ? (
          <GlossaryTerm k={glossaryKey} icon={false}>
            {label}
          </GlossaryTerm>
        ) : (
          label
        )}
      </div>
      <div className="mt-1 text-base font-semibold text-gray-100">{money(value, currency)}</div>
      {probability !== null && probability !== undefined ? (
        <div className="mt-0.5 text-xs text-gray-500">p = {formatPercent(probability, { digits: 0 })}</div>
      ) : null}
    </div>
  );
}

/**
 * Layout estructurado de la tesis: hipotesis, escenarios con probabilidades,
 * scores de calidad, catalizadores con fecha y criterios de invalidacion,
 * seguidos del memorando completo en markdown. Mobile-first: los escenarios
 * apilan en 2 columnas y el resto en 1.
 *
 * Las versiones anteriores a los campos profesionales (hypothesis=null)
 * muestran estados honestos "pendiente", nunca datos inventados.
 */
export default function ThesisMemo({
  thesis,
  ticker,
  currency,
  debateBody,
  modelBlocked = false,
}: {
  thesis: ResearchThesis;
  /** Ticker para el debate bull/bear (bloque interactivo de abajo). */
  ticker?: string;
  /** Divisa del listado (CompanyOut.currency). Sin divisa válida los
   *  importes de la tesis salen como NA, nunca en USD asumido. */
  currency?: string | null;
  /** Cuerpo persistido de la seccion thesis_debate (veredicto previo). */
  debateBody?: string | null;
  /** Modelo fundamental no publicable: la tesis no muestra cifras de valoración. */
  modelBlocked?: boolean;
}) {
  const hideFigures = modelBlocked || (thesis.status !== 'published' && thesis.status !== 'approved');
  const probabilities = thesis.scenario_probabilities ?? {};
  // F394: cada tesis se muestra con SU base persistida; sin evidencia no se escala.
  const scenarios = thesisScenarioDisplay(
    {
      bear: thesis.bear_value,
      base: thesis.base_value,
      bull: thesis.bull_value,
      expected: thesis.expected_value,
    },
    thesis.valuation_basis,
  );
  const generatedLabel = formatGeneratedDate(thesis.created_at);

  // Lo que se lee en voz alta: solo texto persistido y ya visible en esta
  // vista (resumen, narrativa, hipótesis e invalidación). Nada se genera
  // para el audio: si un bloque no existe, no se lee.
  const audioParagraphs = [
    thesis.executive_summary,
    ...(thesis.narrative_sections ?? []).flatMap((section) => [section.titulo, ...section.parrafos]),
    thesis.hypothesis ? `Hipótesis: ${thesis.hypothesis}` : null,
    ...(thesis.invalidation_criteria ?? []).map((criterion) => `Criterio de invalidación: ${criterion}`),
  ].filter((paragraph): paragraph is string => typeof paragraph === 'string' && paragraph.trim().length > 0);

  return (
    <div className="min-w-0 max-w-full space-y-5 [overflow-wrap:anywhere]">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{enumLabel(RATING_LABELS, thesis.rating)}</Badge>
        <Badge variant="outline">{enumLabel(STATUS_LABELS, thesis.status)}</Badge>
        <Badge variant="outline">v{thesis.version}</Badge>
        {generatedLabel ? (
          <span className="text-xs text-gray-500">generada el {generatedLabel}</span>
        ) : null}
        {thesis.stale ? (
          <span className="rounded-full border border-amber-800/60 bg-amber-950/40 px-2.5 py-0.5 text-xs font-medium text-amber-300">
            Datos nuevos disponibles — considera regenerar
          </span>
        ) : null}
      </div>

      {thesis.status === 'insufficient_data' ? (
        <div
          role="status"
          className="rounded-lg border border-amber-800/60 bg-amber-950/20 p-3 text-sm text-amber-200"
        >
          <strong>Tesis provisional</strong>
          <p className="mt-1">
            Publicada con la evidencia disponible. Faltan datos para completarla: la app te los
            pedirá y nunca los inventa.
          </p>
        </div>
      ) : null}

      {thesis.missing_inputs && thesis.missing_inputs.length > 0 ? (
        <section className="rounded-lg border border-amber-800/60 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-200">
            Datos pendientes
          </h3>
          <p className="mt-1 text-xs text-gray-400">
            La tesis se apoya en lo que hay; estos inputs se piden al usuario y, al aportarlos,
            la tesis se regenera.
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-300">
            {thesis.missing_inputs.map((item) => (
              <li key={item}>{frameworkTerm(item) ?? metricLabel(item)}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {thesis.inputs_provenance && thesis.inputs_provenance.length > 0 ? (
        <section className="rounded-lg border border-gray-800 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Procedencia de los inputs
          </h3>
          <div className="mt-2 divide-y divide-gray-800/70">
            {thesis.inputs_provenance.map((item) => {
              return (
                <div key={item.key} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2 text-sm">
                  {isVerifiedOficial(item) ? null : (
                    <span
                      className="rounded-full border border-amber-800 bg-amber-950/40 px-2 py-0.5 text-[11px] font-medium text-amber-300"
                    >
                      INFERIDO
                    </span>
                  )}
                  <span className="order-1 text-gray-300">{capitalizeLabel(metricLabel(item.key))}</span>
                  <span className="order-2 min-w-0 max-w-full ml-auto font-medium tabular-nums text-gray-100">{formatProvenanceValue(item.value, item.unit)}</span>
                  {isVerifiedOficial(item) ? (
                    <span className="order-3 min-w-0 max-w-full basis-full text-xs text-gray-500">
                      ·{' '}
                      {(item.fuentes ?? []).map((fuente, index) => (
                        <span key={fuente.fact_id}>
                          {index > 0 ? ', ' : ''}
                          {fuente.url && /^https:\/\//.test(fuente.url) ? (
                            <a
                              href={fuente.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="break-all text-teal-400 underline"
                            >
                              {fuente.titulo ?? 'Fuente oficial'}
                            </a>
                          ) : (
                            (fuente.titulo ?? 'Fuente oficial')
                          )}
                          {fuente.fecha ? ` (${fuente.fecha})` : ''}
                        </span>
                      ))}
                    </span>
                  ) : (
                    <span className="order-3 min-w-0 max-w-full basis-full text-xs text-amber-400/90">
                      · INFERIDO:{' '}
                      {item.base_documentada !== true || !item.base_inferencia
                        ? 'base no documentada'
                        : `dado ${item.base_inferencia}`}
                      {(item.urls_inferencia ?? []).map((url, index) =>
                        /^https:\/\//.test(url) ? (
                          <a
                            key={url}
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ml-1 text-amber-300 underline"
                          >
                            [{index + 1}]
                          </a>
                        ) : null,
                      )}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {ticker ? <ThesisHumanInputForm ticker={ticker} /> : null}

      <p className="text-sm leading-6 text-gray-300">{cleanThesisText(thesis.executive_summary)}</p>

      {thesis.narrative_sections && thesis.narrative_sections.length > 0 ? (
        <section
          aria-label="Análisis narrativo"
          className="space-y-4 rounded-lg border border-gray-800 bg-gray-900/40 p-4"
        >
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Análisis narrativo
          </h3>
          {thesis.narrative_sections.map((section, index) => (
            <div key={`${section.titulo}-${index}`} className="space-y-2">
              <h4 className="text-sm font-semibold text-gray-200">{section.titulo === 'Lo que cambio' ? 'Lo que cambió' : section.titulo}</h4>
              {section.parrafos.map((parrafo, pIndex) => (
                <p key={pIndex} className="text-sm leading-6 text-gray-300">
                  {cleanThesisText(parrafo)}
                </p>
              ))}
            </div>
          ))}
        </section>
      ) : null}

      <section className="rounded-lg border border-teal-900/60 bg-teal-950/10 p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-teal-300">Hipótesis</h3>
        <p className="mt-2 text-sm leading-6 text-gray-200">
          {cleanThesisText(thesis.hypothesis) ||
            'Pendiente: esta versión es anterior a los campos profesionales. Genera una nueva versión para registrar la hipótesis.'}
        </p>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Escenarios y valoración
        </h3>
        {hideFigures ? (
          <p className="text-sm text-gray-400">
            Sin cifras de valoración: {modelBlocked ? 'el modelo está bloqueado' : 'la tesis es un borrador'}.
          </p>
        ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <ScenarioCell label="Precio" value={thesis.current_price} currency={currency} />
          <ScenarioCell label={`Bear${scenarios.label}`} value={scenarios.values.bear} currency={currency} probability={probabilities['bear']} glossaryKey="bear" />
          <ScenarioCell label={`Base${scenarios.label}`} value={scenarios.values.base} currency={currency} probability={probabilities['base']} highlight glossaryKey="base" />
          <ScenarioCell label={`Bull${scenarios.label}`} value={scenarios.values.bull} currency={currency} probability={probabilities['bull']} glossaryKey="bull" />
          <ScenarioCell label={`Valor esperado${scenarios.label}`} value={scenarios.values.expected} currency={currency} />
          <div className="rounded-lg border border-gray-800 bg-black/20 p-3">
            <div className="text-xs uppercase text-gray-500">
              <GlossaryTerm k="margen_seguridad" icon={false}>
                Margen seguridad
              </GlossaryTerm>
            </div>
            <div className="mt-1 text-base font-semibold text-gray-100">
              {marginOfSafetyDisplay(thesis.margin_of_safety, thesis.base_value)}
            </div>
            {scenarios.values.expected != null ? <div className="mt-0.5 text-xs text-gray-500">sobre valor esperado</div> : null}
          </div>
        </div>
        )}
        {hideFigures ? null : <ScenarioAssumptions />}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Calidad de la evidencia
        </h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ScoreBar label="Confianza en datos" value={thesis.data_confidence_score} />
          <ScoreBar label="Cobertura de fuentes" value={thesis.source_coverage_score} />
          <ScoreBar label="Red team" value={thesis.red_team_score} />
          <ScoreBar label="Riesgo de valoración" value={thesis.valuation_risk_score} />
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-gray-800 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Catalizadores
          </h3>
          {thesis.catalysts && thesis.catalysts.length > 0 ? (
            <ul className="mt-2 space-y-2 text-sm text-gray-300">
              {thesis.catalysts.map((catalyst, index) => (
                <li key={index} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium text-gray-200">{catalyst.label ?? 'Catalizador'}</span>
                  {catalyst.date ? (
                    <span className="text-gray-400">
                      · {catalyst.date}
                      {catalyst.time ? ` ${catalyst.time}` : ''}
                    </span>
                  ) : null}
                  {catalyst.eps_forecast !== undefined ? (
                    <span className="text-gray-500">· EPS est. {thesisEps(catalyst.eps_forecast)}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-gray-500">
              Sin catalizadores con fecha conocida; pendiente del calendario de resultados.
            </p>
          )}
        </section>

        <section className="rounded-lg border border-red-900/50 bg-red-950/10 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-red-300">
            Qué invalidaría la tesis
          </h3>
          {thesis.invalidation_criteria && thesis.invalidation_criteria.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-gray-300">
              {thesis.invalidation_criteria.map((criterion, index) => (
                <li key={index}>{criterion}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-gray-500">
              Pendiente: genera una nueva versión para registrar criterios de invalidación.
            </p>
          )}
        </section>
      </div>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Debate bull/bear
        </h3>
        {ticker ? (
          <ThesisDebatePanel ticker={ticker} initialVerdict={debateBody ?? null} />
        ) : (
          <p className="text-sm text-gray-500">
            Debate no disponible sin ticker: recarga la ficha para contrastar la tesis.
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Memorando completo
        </h3>
        <ThesisMarkdown content={thesis.thesis_markdown} />
      </section>

      {/* Audio básico al final (WorldStocks punto 6): el resumen, la narrativa,
          la hipótesis y los criterios de invalidación, leídos en local. */}
      <ThesisAudioPlayer label={`Tesis de ${ticker ?? 'la empresa'}`} paragraphs={audioParagraphs} />
    </div>
  );
}
