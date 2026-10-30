import { canShowThesisText } from '@/components/research/ThesisSummary';
import { frameworkTerm } from '@/lib/research/framework-terms';
import { thesisMoney, thesisEps } from '@/lib/research/thesis-number-format';
import { thesisScenarioDisplay } from '@/lib/research/listed-share-values';
import { formatGeneratedDate, formatPercent, formatUserDate, isValidCurrencyCode, marginOfSafetyDisplay, NA } from '@/lib/format';
import { PROVENANCE_GROUPS, provenanceBasisEs, provenanceGroup } from '@/lib/research/provenance-groups';
import { isVerifiedOficial, provenanceUrls } from '@/lib/research/provenance-item';
import { capitalizeLabel, formatProvenanceValue } from '@/lib/research/provenance-format';
import { metricLabel } from '@/lib/research/metric-labels';
import { cleanThesisText } from '@/lib/research/thesis-text';
import { GlossaryTerm } from '@/components/GlossaryTerm';
import ScenarioAssumptions from '@/components/research/ScenarioAssumptions';
import ThesisMarkdownPager from '@/components/research/ThesisMarkdownPager';
import { coerceInvalidationRules } from '@/lib/research/thesis-invalidation-rules';

import { splitMemoPages } from '@/lib/research/memo-pages';
import { Badge } from '@/components/ui/badge';
// Las piezas interactivas del memorando (alta de supuestos, reglas de
// invalidación y debate bull/bear) están bajo el pliegue y solo se usan al
// leer la tesis en profundidad: cargan diferidas (ver LazyMemoControls) para
// no inflar el JS inicial de /research/[ticker]. El paginador del memo
// completo se queda eager: es contenido SSR, no una isla interactiva.
import {
  LazyThesisHumanInputForm as ThesisHumanInputForm,
  LazyThesisInvalidationRulesForm as ThesisInvalidationRulesForm,
  LazyThesisDebatePanel as ThesisDebatePanel,
} from '@/components/research/LazyMemoControls';
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
  final: 'generada · pendiente de aprobación',
  draft: 'borrador',
  review: 'en revisión',
  approved: 'aprobada',
  published: 'publicada',
  rejected: 'rechazada',
  stale: 'desactualizada',
  draft_failed_audit: 'borrador (auditoría no superada)',
  changes_requested: 'cambios solicitados',
  insufficient_data: 'datos insuficientes',
};

/** Franjas horarias conocidas del calendario de resultados (misma convencion
 *  que catalyst_calendar_service.py). Los codigos sin etiqueta, como
 *  "time-not-supplied", o desconocidos no se muestran en crudo. */
const CATALYST_TIME_LABELS: Record<string, string> = {
  'time-pre-market': 'antes de la apertura',
  'time-after-hours': 'tras el cierre',
  'before-market': 'antes de la apertura',
  'after-market': 'tras el cierre',
};

function enumLabel(map: Record<string, string>, value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NA;
  return map[value] ?? value.replaceAll('_', ' ');
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

function NarrativeText({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s<>]+)/g);
  return <>{parts.map((part, index) => /^https?:\/\//.test(part)
    ? <a key={index} href={part} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">Fuente</a>
    : <span key={index}>{cleanThesisText(part)}</span>)}</>;
}

function ScoreBar({ label, value, scale = 'quality' }: { label: string; value: number; scale?: 'quality' | 'risk' }) {
  const clamped = Math.max(0, Math.min(100, value));
  // 'quality': cuanto más alto, mejor. 'risk' (riesgo de valoración): cuanto
  // más alto, peor; sin invertir, una especulativa (75/100) salía en verde.
  const good = scale === 'risk' ? clamped < 40 : clamped >= 70;
  const mid = scale === 'risk' ? clamped < 70 : clamped >= 40;
  const tone = good ? 'bg-teal-400' : mid ? 'bg-amber-400' : 'bg-red-400';
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
  caption,
}: {
  label: string;
  value: number | string | null | undefined;
  currency: string | null | undefined;
  probability?: number | null;
  highlight?: boolean;
  glossaryKey?: GlossaryKey;
  /** Línea secundaria bajo el valor (p. ej. la fecha de la cotización). */
  caption?: string | null;
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
      {caption ? <div className="mt-0.5 text-xs text-gray-500">{caption}</div> : null}
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
/** Titulos/parrafos narrativos heredados con la marca «INFERIDO» (prohibida
 *  en UI por decision de Nico, 17-oct): se normalizan al pintar; las tesis
 *  nuevas ya se guardan sin la marca. */
function narrativeTitle(titulo: string): string {
  const fixed = titulo === 'Lo que cambio' ? 'Lo que cambió' : titulo;
  return fixed.replace(/\s*-\s*INFERIDO$/u, '').replace(/\s+INFERIDO$/u, '');
}
function narrativeParagraph(parrafo: string): string {
  return parrafo.replace(/^INFERIDO:\s*/u, '');
}

/** Solo se oculta si es igual o está contenida en el resumen; una hipótesis más larga se conserva entera. */
function hypothesisRepeatsSummary(hypothesis: string | null | undefined, summary: string | null | undefined): boolean {
  const norm = (t: string | null | undefined) => (t ?? '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const h = norm(hypothesis);
  const s = norm(summary);
  return h.length > 0 && s.length > 0 && s.includes(h);
}

export default function ThesisMemo({
  thesis,
  ticker,
  currency,
  debateBody,
  model,
  extraSections = [],
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
  model?: { publishable: boolean } | null;
  /** Secciones específicas de la empresa: van como páginas del memorando. */
  extraSections?: { id: number | string; title: string; body: string }[];
}) {
  const modelBlocked = model?.publishable !== true;
  const hideFigures = !canShowThesisText(thesis, model);
  const withheldReason = modelBlocked ? model?.publishable === false ? 'el modelo no es publicable' : 'no se pudo verificar que el modelo sea publicable' : 'la tesis no está publicada ni aprobada';
  const probabilities = thesis.scenario_probabilities ?? {};
  // Missing provenance stays unknown even against an older backend returning raw margin.
  const knownMargin = thesis.valuation_basis?.margin_of_safety_convention === 'discount_to_value_v1';
  const archivedMargin = thesis.archived_margin_of_safety ?? thesis.margin_of_safety;
  const unknownMargin = !knownMargin && archivedMargin != null;

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
  const ratingBadge = modelBlocked ? 'datos insuficientes' : enumLabel(RATING_LABELS, thesis.rating);
  const statusBadge = enumLabel(STATUS_LABELS, thesis.status);

  return (
    <div className="min-w-0 max-w-full space-y-5 [overflow-wrap:anywhere]">
      {!hideFigures && unknownMargin ? (
        <aside role="note" className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm leading-6 text-amber-200">
          Margen histórico con fórmula no verificada: el porcentaje y el texto originales se conservan como archivo.
          No los compares con el margen actual (V - P) / V ni los uses como señal actual.
        </aside>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{ratingBadge}</Badge>
        {/* Estado y rating son ejes distintos, pero su etiqueta puede coincidir
            («datos insuficientes» en ambos): en ese caso se pinta una sola. */}
        {statusBadge !== ratingBadge ? <Badge variant="outline">{statusBadge}</Badge> : null}
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


      {thesis.status === 'final' ? (
        <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
          Generación completada, pendiente de aprobación. La auditoría automática de fuentes y la aprobación para publicar son pasos distintos; consulta el resultado de la auditoría en Fuentes.
        </p>
      ) : thesis.status !== 'published' && thesis.status !== 'approved' && thesis.status !== 'insufficient_data' ? (
        <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
          Borrador en revisión: texto sin auditar
        </p>
      ) : null}

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
          <div className="mt-3 space-y-4">
            {PROVENANCE_GROUPS.map((group) => {
              const rows = (thesis.inputs_provenance ?? []).filter(
                (item) => provenanceGroup(item.label as string | undefined, isVerifiedOficial(item)) === group.key,
              );
              if (rows.length === 0) return null;
              return (
                <div key={group.key}>
                  <h4 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{group.title}</h4>
                  <dl className="mt-1 divide-y divide-gray-800/70">
                    {rows.map((item) => {
                      const urls = provenanceUrls(item);
                      const basis = provenanceBasisEs(item.base_inferencia ?? item.method);
                      return (
                        <div key={item.key} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2 text-sm">
                          <dt className="text-gray-300">{capitalizeLabel(metricLabel(item.key))}{item.key === 'fcf_margin' ? (item.label === 'derivado' ? ' normalizado' : item.label === 'dato' ? ' reportado' : '') : ''}</dt>
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
                                className="ml-1 text-teal-400 underline"
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

      {ticker ? <ThesisHumanInputForm ticker={ticker} /> : null}

      {hideFigures ? (
        <aside role="note" className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm leading-6 text-amber-200">
          Texto archivado de v{thesis.version}{generatedLabel ? `, generada el ${generatedLabel}` : ', sin fecha de generación verificada'}: resumen, narrativa y memorando retenidos porque {withheldReason}.
          {' '}Pueden contener cifras de valoración antiguas sin verificar; no se presentan como análisis actual. El original se conserva guardado, sin cambios.
        </aside>
      ) : <p className="text-sm leading-6 text-gray-300">{cleanThesisText(thesis.executive_summary)}</p>}

      {!hideFigures && thesis.narrative_sections && thesis.narrative_sections.length > 0 ? (
        <section
          aria-label="Análisis narrativo"
          className="space-y-4 rounded-lg border border-gray-800 bg-gray-900/40 p-4"
        >
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Análisis narrativo
          </h3>
          {thesis.narrative_sections.map((section, index) => (
            <div key={`${section.titulo}-${index}`} className="space-y-2">
              <h4 className="text-sm font-semibold text-gray-200">{narrativeTitle(section.titulo)}</h4>
              {section.parrafos.map((parrafo, pIndex) => (
                <p key={pIndex} className="text-sm leading-6 text-gray-300">
                  <NarrativeText text={narrativeParagraph(parrafo)} />
                </p>
              ))}
            </div>
          ))}
        </section>
      ) : null}

      {hideFigures || hypothesisRepeatsSummary(thesis.hypothesis, thesis.executive_summary) ? null : (
  <section className="rounded-lg border border-teal-900/60 bg-teal-950/10 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-teal-300">Hipótesis</h3>
          <p className="mt-2 text-sm leading-6 text-gray-200">
            {cleanThesisText(thesis.hypothesis) ||
              'Pendiente: esta versión es anterior a los campos profesionales. Genera una nueva versión para registrar la hipótesis.'}
          </p>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Escenarios y valoración
        </h3>
        {hideFigures ? (
          <p className="text-sm text-gray-400">
            Sin cifras de valoración: {withheldReason}. El texto guardado también se retiene para no mostrar esas cifras por otra vía.
          </p>
        ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {/* El precio guardado es el que usó el modelo al generar la versión,
              no la cotización de hoy; la fecha solo si quedó persistida. */}
          <ScenarioCell
            label="Precio del modelo"
            value={thesis.current_price}
            currency={currency}
            caption={thesis.valuation_basis?.price_as_of ? `cotización al ${formatUserDate(thesis.valuation_basis.price_as_of)}` : null}
          />
          <ScenarioCell label={`Bear${scenarios.label}`} value={scenarios.values.bear} currency={currency} probability={probabilities['bear']} glossaryKey="bear" />
          <ScenarioCell label={`Base${scenarios.label}`} value={scenarios.values.base} currency={currency} probability={probabilities['base']} highlight glossaryKey="base" />
          <ScenarioCell label={`Bull${scenarios.label}`} value={scenarios.values.bull} currency={currency} probability={probabilities['bull']} glossaryKey="bull" />
          <ScenarioCell label={`Valor esperado${scenarios.label}`} value={scenarios.values.expected} currency={currency} />
          <div className="rounded-lg border border-gray-800 bg-black/20 p-3">
            <div className="text-xs uppercase text-gray-500">
              <GlossaryTerm k="margen_seguridad" icon={false}>
                {unknownMargin ? 'Margen archivado' : 'Margen seguridad'}
              </GlossaryTerm>
            </div>
            <div className="mt-1 text-base font-semibold text-gray-100">
              {marginOfSafetyDisplay(knownMargin ? thesis.margin_of_safety : archivedMargin, thesis.base_value)}
            </div>
            <div className="mt-0.5 text-xs text-gray-500">
              {unknownMargin ? 'Fórmula no verificada; no comparable' : knownMargin ? '(V - P) / V · base del modelo de esta versión' : 'Sin margen registrado'}
            </div>
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
          <ScoreBar label="Riesgo de valoración" value={thesis.valuation_risk_score} scale="risk" />
        </div>
      </section>

      {!hideFigures ? <div className="grid gap-4 lg:grid-cols-2">
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
                      {catalyst.time && CATALYST_TIME_LABELS[catalyst.time] ? ` ${CATALYST_TIME_LABELS[catalyst.time]}` : ''}
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
          {ticker ? (
            <ThesisInvalidationRulesForm
              ticker={ticker}
              initialRules={coerceInvalidationRules(thesis.invalidation_rules)}
            />
          ) : null}
        </section>
      </div> : null}

      {!hideFigures ? <section>
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
      </section> : null}

      {!hideFigures ? <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Memorando completo
        </h3>
        <ThesisMarkdownPager
          pages={[
            ...splitMemoPages(thesis.thesis_markdown),
            ...extraSections
              .filter((section) => section.body?.trim())
              .map((section) => ({ id: `s${section.id}`, title: section.title, body: `## ${section.title}\n\n${section.body}` })),
          ]}
        />
      </section> : null}
    </div>
  );
}
