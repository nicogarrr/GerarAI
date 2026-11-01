import { canShowThesisText } from '@/components/research/ThesisSummary';
import { frameworkTerm } from '@/lib/research/framework-terms';
import { thesisMoney, thesisEps } from '@/lib/research/thesis-number-format';
import { thesisScenarioDisplay } from '@/lib/research/listed-share-values';
import { createFormatters, isValidCurrencyCode, type Formatters, marginOfSafetyDisplay, NA } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';
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

const RATING_KEYS: Record<string, TranslationKey> = {
  buy: 'research.memo.ratingBuy', accumulate: 'research.memo.ratingAccumulate', overweight: 'research.memo.ratingOverweight',
  hold: 'research.memo.ratingHold', underweight: 'research.memo.ratingUnderweight', trim: 'research.memo.ratingTrim',
  sell: 'research.memo.ratingSell', avoid: 'research.memo.ratingAvoid', watch: 'research.memo.ratingWatch',
  attractive: 'research.memo.ratingAttractive', expensive: 'research.memo.ratingExpensive',
  incomplete_price: 'research.memo.ratingIncompletePrice', blocked: 'research.memo.ratingBlocked', insufficient_data: 'research.memo.insufficientData',
};

const STATUS_KEYS: Record<string, TranslationKey> = {
  final: 'research.memo.statusFinal', draft: 'research.memo.statusDraft', review: 'research.memo.statusReview',
  approved: 'research.memo.statusApproved', published: 'research.memo.statusPublished', rejected: 'research.memo.statusRejected',
  stale: 'research.memo.statusStale', draft_failed_audit: 'research.memo.statusDraftFailedAudit',
  changes_requested: 'research.memo.statusChangesRequested', insufficient_data: 'research.memo.insufficientData',
};

const CATALYST_TIME_KEYS: Record<string, TranslationKey> = {
  'time-pre-market': 'research.memo.beforeOpen', 'time-after-hours': 'research.memo.afterClose',
  'before-market': 'research.memo.beforeOpen', 'after-market': 'research.memo.afterClose',
};

const PROVENANCE_GROUP_KEYS: Record<string, TranslationKey> = {
  reportado: 'research.memo.provReported', sin_verificar: 'research.memo.provUnverified',
  calculado: 'research.memo.provCalculated', supuesto: 'research.memo.provAssumption',
};

/** Etiqueta traducida de un enum conocido; los desconocidos siguen por enumLabel. */
function keyedLabel(t: TranslateFn, keys: Record<string, TranslationKey>, value: string | null | undefined): string | null {
  return value && Object.hasOwn(keys, value) ? t(keys[value]) : null;
}

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

function NarrativeText({ text, sourceLabel }: { text: string; sourceLabel: string }) {
  const parts = text.split(/(https?:\/\/[^\s<>]+)/g);
  return <>{parts.map((part, index) => /^https?:\/\//.test(part)
    ? <a key={index} href={part} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">{sourceLabel}</a>
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
  formatPercent,
}: {
  formatPercent: Formatters['formatPercent'];
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
  locale = 'es',
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
  /** Idioma elegido (por defecto el español de referencia). */
  locale?: Locale;
}) {
  const t = createTranslator(locale);
  const { formatGeneratedDate, formatPercent, formatUserDate } = createFormatters(locale);
  const modelBlocked = model?.publishable !== true;
  const hideFigures = !canShowThesisText(thesis, model);
  const withheldReason = modelBlocked ? model?.publishable === false ? t('research.memo.withheldNotPublishable') : t('research.memo.withheldUnverified') : t('research.memo.withheldNotPublished');
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
  const ratingBadge = modelBlocked ? t('research.memo.insufficientData') : keyedLabel(t, RATING_KEYS, thesis.rating) ?? enumLabel(RATING_LABELS, thesis.rating);
  const statusBadge = keyedLabel(t, STATUS_KEYS, thesis.status) ?? enumLabel(STATUS_LABELS, thesis.status);

  return (
    <div className="min-w-0 max-w-full space-y-5 [overflow-wrap:anywhere]">
      {!hideFigures && unknownMargin ? (
        <aside role="note" className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm leading-6 text-amber-200">
          {t('research.memo.archivedMarginNote')}
        </aside>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{ratingBadge}</Badge>
        {/* Estado y rating son ejes distintos, pero su etiqueta puede coincidir
            («datos insuficientes» en ambos): en ese caso se pinta una sola. */}
        {statusBadge !== ratingBadge ? <Badge variant="outline">{statusBadge}</Badge> : null}
        <Badge variant="outline">v{thesis.version}</Badge>
        {generatedLabel ? (
          <span className="text-xs text-gray-500">{t('research.memo.generatedOn', { date: generatedLabel })}</span>
        ) : null}
        {thesis.stale ? (
          <span className="rounded-full border border-amber-800/60 bg-amber-950/40 px-2.5 py-0.5 text-xs font-medium text-amber-300">
            {t('research.memo.staleData')}
          </span>
        ) : null}
      </div>


      {thesis.status === 'final' ? (
        <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
          {t('research.memo.finalPending')}
        </p>
      ) : thesis.status !== 'published' && thesis.status !== 'approved' && thesis.status !== 'insufficient_data' ? (
        <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
          {t('research.memo.draftReview')}
        </p>
      ) : null}

      {thesis.status === 'insufficient_data' ? (
        <div
          role="status"
          className="rounded-lg border border-amber-800/60 bg-amber-950/20 p-3 text-sm text-amber-200"
        >
          <strong>{t('research.memo.provisionalTitle')}</strong>
          <p className="mt-1">
            {t('research.memo.provisionalBody')}
          </p>
        </div>
      ) : null}

      {thesis.missing_inputs && thesis.missing_inputs.length > 0 ? (
        <section className="rounded-lg border border-amber-800/60 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-200">
            {t('research.memo.missingTitle')}
          </h3>
          <p className="mt-1 text-xs text-gray-400">
            {t('research.memo.missingBody')}
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
            {t('research.memo.provenanceTitle')}
          </h3>
          <div className="mt-3 space-y-4">
            {PROVENANCE_GROUPS.map((group) => {
              const rows = (thesis.inputs_provenance ?? []).filter(
                (item) => provenanceGroup(item.label as string | undefined, isVerifiedOficial(item)) === group.key,
              );
              if (rows.length === 0) return null;
              return (
                <div key={group.key}>
                  <h4 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{keyedLabel(t, PROVENANCE_GROUP_KEYS, group.key) ?? group.title}</h4>
                  <dl className="mt-1 divide-y divide-gray-800/70">
                    {rows.map((item) => {
                      const urls = provenanceUrls(item);
                      const basis = provenanceBasisEs(item.base_inferencia ?? item.method);
                      return (
                        <div key={item.key} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2 text-sm">
                          <dt className="text-gray-300">{capitalizeLabel(metricLabel(item.key))}{item.key === 'fcf_margin' ? (item.label === 'derivado' ? ` ${t('research.memo.fcfNormalized')}` : item.label === 'dato' ? ` ${t('research.memo.fcfReported')}` : '') : ''}</dt>
                          <dd className="ml-auto font-medium tabular-nums text-gray-100">{formatProvenanceValue(item.value, item.unit)}</dd>
                          <dd className="basis-full text-xs text-gray-500">
                            {basis ?? t('research.memo.basisUndocumented')}
                            {urls.map((url, index) => (
                              <a
                                key={url}
                                href={url}
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label={t('research.memo.sourceN', { n: index + 1 })}
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
          {generatedLabel ? t('research.memo.withheldArchivedDated', { version: thesis.version, date: generatedLabel, reason: withheldReason }) : t('research.memo.withheldArchivedUndated', { version: thesis.version, reason: withheldReason })}
          {' '}{t('research.memo.withheldArchivedNote')}
        </aside>
      ) : <p className="text-sm leading-6 text-gray-300">{cleanThesisText(thesis.executive_summary)}</p>}

      {!hideFigures && thesis.narrative_sections && thesis.narrative_sections.length > 0 ? (
        <section
          aria-label={t('research.memo.narrative')}
          className="space-y-4 rounded-lg border border-gray-800 bg-gray-900/40 p-4"
        >
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            {t('research.memo.narrative')}
          </h3>
          {thesis.narrative_sections.map((section, index) => (
            <div key={`${section.titulo}-${index}`} className="space-y-2">
              <h4 className="text-sm font-semibold text-gray-200">{narrativeTitle(section.titulo)}</h4>
              {section.parrafos.map((parrafo, pIndex) => (
                <p key={pIndex} className="text-sm leading-6 text-gray-300">
                  <NarrativeText text={narrativeParagraph(parrafo)} sourceLabel={t('research.memo.source')} />
                </p>
              ))}
            </div>
          ))}
        </section>
      ) : null}

      {hideFigures || hypothesisRepeatsSummary(thesis.hypothesis, thesis.executive_summary) ? null : (
  <section className="rounded-lg border border-teal-900/60 bg-teal-950/10 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-teal-300">{t('research.memo.hypothesis')}</h3>
          <p className="mt-2 text-sm leading-6 text-gray-200">
            {cleanThesisText(thesis.hypothesis) ||
              t('research.memo.hypothesisPending')}
          </p>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          {t('research.memo.scenarios')}
        </h3>
        {hideFigures ? (
          <p className="text-sm text-gray-400">
            {t('research.memo.withheldFigures', { reason: withheldReason })}
          </p>
        ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {/* El precio guardado es el que usó el modelo al generar la versión,
              no la cotización de hoy; la fecha solo si quedó persistida. */}
          <ScenarioCell formatPercent={formatPercent}
            label={t('research.memo.modelPrice')}
            value={thesis.current_price}
            currency={currency}
            caption={thesis.valuation_basis?.price_as_of ? t('research.memo.quoteAsOf', { date: formatUserDate(thesis.valuation_basis.price_as_of) }) : null}
          />
          <ScenarioCell formatPercent={formatPercent} label={`Bear${scenarios.label}`} value={scenarios.values.bear} currency={currency} probability={probabilities['bear']} glossaryKey="bear" />
          <ScenarioCell formatPercent={formatPercent} label={`Base${scenarios.label}`} value={scenarios.values.base} currency={currency} probability={probabilities['base']} highlight glossaryKey="base" />
          <ScenarioCell formatPercent={formatPercent} label={`Bull${scenarios.label}`} value={scenarios.values.bull} currency={currency} probability={probabilities['bull']} glossaryKey="bull" />
          <ScenarioCell formatPercent={formatPercent} label={`${t('research.memo.expectedValue')}${scenarios.label}`} value={scenarios.values.expected} currency={currency} />
          <div className="rounded-lg border border-gray-800 bg-black/20 p-3">
            <div className="text-xs uppercase text-gray-500">
              <GlossaryTerm k="margen_seguridad" icon={false}>
                {unknownMargin ? t('research.memo.archivedMargin') : t('research.memo.marginOfSafety')}
              </GlossaryTerm>
            </div>
            <div className="mt-1 text-base font-semibold text-gray-100">
              {marginOfSafetyDisplay(knownMargin ? thesis.margin_of_safety : archivedMargin, thesis.base_value)}
            </div>
            <div className="mt-0.5 text-xs text-gray-500">
              {unknownMargin ? t('research.memo.marginUnverified') : knownMargin ? t('research.memo.marginFormula') : t('research.memo.marginNone')}
            </div>
          </div>
        </div>
        )}
        {hideFigures ? null : <ScenarioAssumptions />}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          {t('research.memo.evidenceQuality')}
        </h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ScoreBar label={t('research.memo.dataConfidence')} value={thesis.data_confidence_score} />
          <ScoreBar label={t('research.memo.sourceCoverage')} value={thesis.source_coverage_score} />
          <ScoreBar label={t('research.memo.redTeam')} value={thesis.red_team_score} />
          <ScoreBar label={t('research.memo.valuationRisk')} value={thesis.valuation_risk_score} scale="risk" />
        </div>
      </section>

      {!hideFigures ? <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-gray-800 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            {t('research.memo.catalysts')}
          </h3>
          {thesis.catalysts && thesis.catalysts.length > 0 ? (
            <ul className="mt-2 space-y-2 text-sm text-gray-300">
              {thesis.catalysts.map((catalyst, index) => (
                <li key={index} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium text-gray-200">{catalyst.label ?? t('research.memo.catalyst')}</span>
                  {catalyst.date ? (
                    <span className="text-gray-400">
                      · {catalyst.date}
                      {catalyst.time && CATALYST_TIME_LABELS[catalyst.time] ? ` ${keyedLabel(t, CATALYST_TIME_KEYS, catalyst.time) ?? CATALYST_TIME_LABELS[catalyst.time]}` : ''}
                    </span>
                  ) : null}
                  {catalyst.eps_forecast !== undefined ? (
                    <span className="text-gray-500">· {t('research.memo.epsEstimate')} {thesisEps(catalyst.eps_forecast)}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-gray-500">
              {t('research.memo.noCatalysts')}
            </p>
          )}
        </section>

        <section className="rounded-lg border border-red-900/50 bg-red-950/10 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-red-300">
            {t('research.memo.invalidation')}
          </h3>
          {thesis.invalidation_criteria && thesis.invalidation_criteria.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-gray-300">
              {thesis.invalidation_criteria.map((criterion, index) => (
                <li key={index}>{criterion}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-gray-500">
              {t('research.memo.invalidationPending')}
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
          {t('research.memo.debate')}
        </h3>
        {ticker ? (
          <ThesisDebatePanel ticker={ticker} initialVerdict={debateBody ?? null} />
        ) : (
          <p className="text-sm text-gray-500">
            {t('research.memo.debateNoTicker')}
          </p>
        )}
      </section> : null}

      {!hideFigures ? <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          {t('research.memo.fullMemo')}
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
