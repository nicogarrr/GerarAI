import { getLocale, getT } from '@/lib/i18n/server';
import { RATING_LABELS_EN, STATUS_LABELS_EN } from '@/lib/research/status-labels-en';
import type { TranslationKey } from '@/lib/i18n/t';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';
import { getParticipationFilings } from '@/lib/actions/research.actions';
import { ParticipationFilingsPanel } from '@/components/research/ParticipationFilingsPanel';
import { FactTable } from '@/components/research/FactsPanels';
import BlockedValuation from '@/components/research/BlockedValuation';
import { ThesisSummary } from '@/components/research/ThesisSummary';
import { CompanyNavigation } from '@/components/research/CompanyNavigation';
import BrainAskForm from '@/components/research/BrainAskForm';
import LegacyChatRedirect from '@/components/research/LegacyChatRedirect';
import { ResearchHashScroll } from '@/components/research/ResearchHashScroll';
import { formatResearchMetric } from '@/lib/research/metric-value';
import { financialFormula, financialPeriod, financialVersionLabel } from '@/lib/research/financial-display';
import { changeSummaryText } from '@/lib/research/change-copy';
import { ownershipLimitations } from '@/lib/research/ownership-display';
import ThesisAudioPlayer from '@/components/research/ThesisAudioPlayer';
import MobileCollapse from '@/components/ui/mobile-collapse';
import CompanyActionsMenu from '@/components/research/CompanyActionsMenu';
import { collapseVersionHistory, versionHistoryBadges } from '@/lib/research/version-history';
import { ListingStaleBanner } from '@/components/research/ListingStaleBanner';
import { formatPeerValue, peerMedianText } from '@/lib/research/peer-format';
import { groupClaimsByVersion } from '@/lib/research/claim-groups';
import { asView, tabHref, tabOfView, type View } from '@/lib/research/research-views';
import { FinancialTerminalSection } from '@/components/research/sections/FinancialTerminalSection';
import { ShareCapitalSection } from '@/components/research/sections/ShareCapitalSection';
import { DriverAssumptionsSection } from '@/components/research/sections/DriverAssumptionsSection';
import { ManagementCredibilitySection } from '@/components/research/sections/ManagementCredibilitySection';
import { DecisionLessonsSection } from '@/components/research/sections/DecisionLessonsSection';
import { SectionLoadError } from '@/components/research/sections/SectionLoadError';
import { QuickGlancePanel } from '@/components/research/QuickGlancePanel';
import { getAnalystTargets } from '@/lib/research/analyst-targets';
import { getKeyStats } from '@/lib/research/key-stats';
import { researchValuability, visibleThesisRating } from '@/lib/research/coverage-state';
import type { Metadata } from 'next';
import Link from 'next/link';
import { getProfile } from '@/lib/actions/finnhub.actions';
import { resolveUnknownListingIdentity } from '@/lib/research/unknown-listing';
import { checkCompanyIdentity, openVerifiedFicha } from '@/lib/actions/company-identity.actions';
import { drainRejection } from '@/lib/research/drain-rejection';
import { cache, Suspense } from 'react';
import { redirect } from 'next/navigation';
import { canonicalRedirectTicker } from '@/lib/research/canonical-ticker';
import {
  ArrowLeft,
  FileText,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  Target,
} from 'lucide-react';

import { researchRequest } from '@/lib/research/client';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import type { ExtendedQuote } from '@/lib/market/extended-quote';
import { isE2EMarketFixtureEnabled } from '@/lib/e2e-market-fixture';
import { e2eExtendedQuoteFixture } from '@/lib/e2e-extended-quote-fixture';
import { MoatTerm } from '@/components/GlossaryTerm';
import { MutationForm } from '@/components/forms/MutationForm';
import { ResearchClaimForm } from '@/components/research/ResearchClaimForm';
// El input de subida (procesa imágenes en canvas) solo aparece en la vista de
// documentos: carga diferido (ver FileUploadInputLazy) para que su JS no
// viaje en la ficha inicial.
import { FileUploadInputLazy as FileUploadInput } from '@/components/forms/FileUploadInputLazy';
import { CompanyHeaderQuote } from '@/components/research/CompanyHeaderQuote';
import { CompanyHeaderQuoteSkeleton } from '@/components/research/CompanyHeaderQuoteSkeleton';
import { ChangesSinceVisit } from '@/components/research/ChangesSinceVisit';
import { DocumentsList } from '@/components/research/DocumentsList';
import { ChangesFeed } from '@/components/research/ChangesFeed';
import { AnalystTargetsSection } from '@/components/research/AnalystTargetsSection';
import { DcaHitRatesSection } from '@/components/research/DcaHitRatesSection';
import { TtmPanel } from '@/components/research/TtmPanel';
import { GuideContextPanel } from '@/components/research/GuideContextPanel';
import { getGuideContext } from '@/lib/research/assistant-client';
import { CompanyPaperTrades } from '@/components/research/CompanyPaperTrades';
import { CompanyPositionPanel } from '@/components/research/CompanyPositionPanel';
import { getCompanyHolding } from '@/lib/actions/portfolio.actions';
import { getCompanyPaperTrades } from '@/lib/actions/paper-trading.actions';
import { ChatIntentLinks } from '@/components/research/ChatIntentLinks';
import { NextStepLink } from '@/components/research/NextStepLink';
import { missingLayerAction, missingLayerLabel } from '@/lib/research/missing-layer-guidance';
import { metricLabel } from '@/lib/research/metric-labels';
import { MoatPanel, MoatClassificationPanel, MoatChecklistPanel } from '@/components/research/MoatPanel';
import { AstOrbitPanel } from '@/components/research/AstOrbitPanel';
import { ThesisScenariosPanel } from '@/components/research/ThesisScenariosPanel';
import { getThesisWithScenarios } from '@/lib/actions/thesis-scenarios.actions';
import { getAstOrbitOverview, getAstsAnalysis } from '@/lib/actions/asts-orbits.actions';
import {
  DecisionAndRealityPanel,
  LongTermModelPanel,
  termLabel,
} from '@/components/research/FundamentalModelPanels';
import { Badge } from '@/components/ui/badge';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { exchangeDisplayName } from '@/lib/exchangeName';
import { auditScoreText, auditStatusLabel, sortAuditsRecentFirst } from '@/lib/audit-status-copy';
import { companyTypeLabel, etiquetaTierFuente,
  tierRankFuente, etiquetaValor, sectorIndustryLine } from '@/lib/labels';
import { Button } from '@/components/ui/button';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Panel } from '@/components/ui/panel';
import { PagedList } from '@/components/ui/pagination';
import { Stat } from '@/components/ui/stat';
import { getCompanyPer } from '@/lib/actions/company-per.actions';
import {
  createResearchClaim,
  getResearchChangesWorkspace,
  getResearchCompanySnapshot,
  getResearchDocumentsWorkspace,
  getResearchFinancialsWorkspace,
  getResearchLongTermModel,
  getResearchMoatWorkspace,
  getResearchPeersWorkspace,
  getResearchSourceAuditsWorkspace,
  getResearchValuationWorkspace,
  importResearchDocumentFile,
  importResearchDocumentUrl,
  refreshCompanyFinancials,
  refreshCompanyFinancialsESEF,
  refreshCompanyFinancialsSEC,
  refreshCompanyResearchModel,
  type ResearchCalculatedMetric,
  type ResearchLongTermModel,
  type ResearchValuation,
  getMoatQualityScore,
  getResearchNews,
} from '@/lib/actions/research.actions';
import { getCompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { getCompanyHolders } from '@/lib/actions/investors.actions';
import { getShareCapital } from '@/lib/actions/share-capital.actions';
import { getDecisionLessons, getDriverAssumptions, getFinancialTerminal, getManagementCredibility } from '@/lib/actions/research-tools.actions';
import { getKnowledgeDocumentsForTicker } from '@/lib/actions/research-tools.actions';
import { libraryDocumentHref } from '@/lib/knowledge/document-ticker';
import { getWatchlist } from '@/lib/actions/watchlist.actions';
import BackendOffline from '@/components/system/BackendOffline';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { findUnavailableViewFailure, viewRetryHref } from '@/lib/research/view-outage';
import QuickAlertButton from '@/components/research/QuickAlertButton';
import ThesisMemo from '@/components/research/ThesisMemo';
import { valuationScenarioDisplay } from '@/lib/research/listed-share-values';
import { baseAssumptionsText, blockerLabel, reverseDcfText, scenarioNotesList } from '@/lib/research/valuation-display';
import ThesisExportMenu from '@/components/research/ThesisExportMenu';
import { NewsHeadline } from '@/components/research/NewsHeadline';
import { ImpactBadge, NewsEventsFlow } from '@/components/research/NewsEventsFlow';
import { NEWS_PAGE_SIZE } from '@/lib/news-paging';
import { getTickerContext } from '@/lib/actions/ticker-context.actions';
import { SourceAuditDetail } from '@/components/research/SourceAuditDetail';
import { dedupeNewsEvents, newsDisplayTitle } from '@/lib/news-display';
import ThesisApproveButton from '@/components/research/ThesisApproveButton';
import FollowButton from '@/components/screener/FollowButton';
import ThesisGenerateButton from '@/components/research/ThesisGenerateButton';
import { createFormatters, formatDate, formatMarketCapUsd, formatMarketDate, formatNumber, formatUserDate, formatUserDateTime, formatMoney, formatPrice, isValidCurrencyCode, NA } from '@/lib/format';
import { getInsiderFilings, getOwnershipSignals } from '@/lib/actions/insider.actions';
import { OwnershipSignalsPanel } from '@/components/research/OwnershipSignalsPanel';
import { insiderName, insiderRole } from '@/lib/insider/format';
import { glossary, moatGlossaryKey } from '@/lib/glossary';
import {
  RESEARCH_RENDER_BUDGET_MS,
  pick,
  settleResearchBatch,
} from '@/lib/research/parallel-fetch';
import type { ResearchSettled } from '@/lib/research/parallel-fetch';
import { withResearchTelemetry } from '@/lib/research/fetch-telemetry';
import { assertTickerShape } from '@/lib/research/assert-ticker-shape';

export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const maxDuration = 60;

/**
 * El snapshot alimenta la página y el título. Sin esta memoización, el
 * `generateMetadata` y el render de la página abrirían dos veces la misma
 * llamada (`cache: 'no-store'` no deduplica).
 */
const readSnapshot = cache((ticker: string) => getResearchCompanySnapshot(ticker));

/* Los 3 pasos (Entender/Valorar/Seguir) y sus 18 modulos viven en
   lib/research/research-views.ts; test funcional: scripts/research-views-guard.test.ts. */

type PageProps = {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ view?: string; chat?: string; pagina?: string; metrics?: string; years?: string; periodicity?: string }>;
};


/** Fecha de la noticia con su provenance: nunca afirmar fecha de publicacion
 *  cuando es el fallback de ingesta o no hay metadato. */
function newsDateLabel(event: { date: string; date_source?: string | null }, t: TranslateFn, locale: Locale): string {
  // es-ES («16 oct 2026»), no ISO crudo: el resto de la app ya pinta así.
  const day = formatUserDate(event.date, undefined, undefined, locale);
  // Mismo criterio que NewsEventsFlow y ResearchAssistant: solo 'source' es
  // fecha de publicacion verificada; el resto se etiqueta, nunca se afirma.
  if (event.date_source === 'source') return day;
  if (event.date_source === 'gdelt_first_seen') return t('research.ficha.dateDetected', { date: day });
  if (event.date_source === 'ingested_at_fallback') return t('research.ficha.dateIngested', { date: day });
  return t('research.ficha.dateUnverified', { date: day });
}

function number(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Etiquetas en español para enums persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
  final: 'generada · pendiente de aprobación',
  draft: 'borrador',
  review: 'en revisión',
  approved: 'aprobada',
  published: 'publicada',
  rejected: 'rechazada',
  changes_requested: 'cambios solicitados',
  'changes requested': 'cambios solicitados',
  draft_failed_audit: 'borrador (auditoría no superada)',
  superseded: 'sustituida',
  stale: 'desactualizada',
  proposed: 'propuesta',
  unknown: 'desconocido',
  low: 'baja',
  medium: 'media',
  high: 'alta',
  supported: 'respaldada',
  refuted: 'refutada',
  open: 'abierta',
  available: 'disponible',
  ok: 'disponible',
  unavailable: 'no disponible',
  partial: 'parcial',
  missing: 'faltante',
  blocked: 'bloqueada',
  insufficient_data: 'datos insuficientes',
  positive: 'positivo',
  negative: 'negativo',
  neutral: 'neutral',
  mixed: 'mixto',
  up: 'al alza',
  down: 'a la baja',
  operating_company: 'empresa operativa',
  research_candidate: 'candidato de análisis',
  fund: 'fondo',
  etf: 'ETF',
  trust: 'trust',
  rising: 'al alza',
  falling: 'a la baja',
  stable: 'estable',
};

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
  // Ratings del motor de tesis (thesis_service._rating): eje de valoracion,
  // no de recomendacion.
  attractive: 'atractiva',
  expensive: 'cara',
  incomplete_price: 'precio incompleto',
};

/** F24 (vista Comparables): etiquetas/prosa del backend en español,
 *  con fallback al original para no ocultar datos si el backend cambia. */
const PEERS_BASIS_KEYS: Record<string, TranslationKey> = {
  traceable_calculated_metric: 'research.peers.basisTraceable',
  evidence_backed_claim: 'research.peers.basisEvidence',
};
const PEERS_METHODOLOGY_KEYS: Record<string, TranslationKey> = {
  'Quantitative differences use traceable calculated metrics. Qualitative differences are emitted only when linked evidence exists.':
    'research.peers.methodology',
};

/**
 * El título de la ficha. Antes todas las empresas comparten el mismo `<title>`
 * (solo lo añadía el template "%s | GerarAI"), que es la mayor pérdida de SEO y
 * de identificación de la app: en la pestaña, en el historial y al compartir
 * no se distinguía una ficha de otra. El nombre sale del mismo snapshot que
 * pinta la página; si el backend no responde, se queda el ticker, que ya
 * identifica la ficha.
 */
export async function generateMetadata({ params }: Pick<PageProps, 'params'>): Promise<Metadata> {
  const { ticker: rawTicker } = await params;
  const ticker = rawTicker.trim().toUpperCase();
  let name: string | null = null;
  try {
    name = (await readSnapshot(ticker))?.company.name ?? null;
  } catch {
    name = null;
  }
  const subject = name ? `${ticker} · ${name}` : ticker;
  return {
    title: subject,
    description: (await getT())('research.identity.metaDescription', { subject: name ?? ticker }),
  };
}

function label(value: string | null | undefined, locale: Locale = 'es'): string {
  if (value === null || value === undefined || value === '') return NA;
  if (locale === 'en') return STATUS_LABELS_EN[value] ?? RATING_LABELS_EN[value] ?? etiquetaValor(value);
  return STATUS_LABELS[value] ?? RATING_LABELS[value] ?? etiquetaValor(value);
}

/**
 * F249: source_url se persiste tal cual en varios caminos de ingesta, así
 * que no basta con que sea truthy: solo se enlaza una URL absoluta
 * http(s) con hostname. Cualquier otra cosa (javascript:, data:,
 * relativa, malformada) se queda como texto plano.
 */
function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if ((url.protocol === 'https:' || url.protocol === 'http:') && url.hostname) {
      return url.toString();
    }
  } catch {
    // malformada: texto plano
  }
  return null;
}

/** Definición metodológica del foso (glosario compartido) para pintarla en la card */
function moatDefinition(type: string): string | null {
  const key = moatGlossaryKey[type];
  return key ? glossary[key].short : null;
}

function metricValue(value: number | string | null | undefined, unit: string, t: TranslateFn) {
  const parsed = number(value);
  if (parsed === null) return t('research.ficha.unknownValue');
  return formatResearchMetric(parsed, unit);
}

/** Un borrador o una tesis en revisión no enseña veredicto ni cifras (regla vigente, igual que el memo y el PDF). */
function thesisIsPublic(status: string | null | undefined): boolean {
  return status === 'published' || status === 'approved';
}

async function MetricsGrid({ metrics }: { metrics: ResearchCalculatedMetric[] }) {
  const t = await getT();
  const locale = await getLocale();
  if (!metrics.length) {
    return (
      <EmptyState
        description={t('research.ficha.metricsEmptyDescription')}
        title={t('research.ficha.metricsEmptyTitle')}
      />
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {metrics.map((metric) => (
        <div className="rounded-lg border border-gray-800 p-4" key={`${metric.metric}-${metric.period}-${metric.definition_version}`}>
          {/* F320: el nombre de métrica es un token largo irrompible
              (net_debt_to_ebitda): sin min-w-0/break-all empujaba el badge
              fuera de la tarjeta a 768px. */}
          <div className="flex items-center justify-between gap-3">
            <span className="min-w-0 break-all font-medium text-gray-200">{metricLabel(metric.metric, locale)}</span>
            <Badge className="shrink-0" variant="outline">{label(metric.status, locale)}</Badge>
          </div>
          <div className="mt-2 text-xl text-teal-300">{metricValue(metric.value, metric.unit, t)}</div>
          <div className="mt-2 text-xs text-gray-500">{financialPeriod(metric.period, locale)} · {financialVersionLabel(metric.definition_version, locale)}</div>
          <div className="mt-2 text-xs leading-5 text-gray-400">{financialFormula(metric.formula, locale)}</div>
        </div>
      ))}
    </div>
  );
}

async function ValuationView({ valuation, currency, ticker }: { valuation: ResearchValuation | null; currency: string; ticker: string }) {
  const t = await getT();
  const locale = await getLocale();
  if (!valuation) {
    return (
      <EmptyState
        action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>{t('research.ficha.valuationEmptyAction')}</EmptyLink>}
        title={t('research.ficha.valuationEmptyTitle')}
      />
    );
  }
  if (valuation.status === 'insufficient_data') {
    return <BlockedValuation valuation={valuation} ticker={ticker} locale={locale} />;
  }
  const engine = typeof valuation.trace?.engine === 'string' ? valuation.trace.engine : null;
  const method = typeof valuation.trace?.method === 'string' ? valuation.trace.method : null;
  const periods = Object.entries(valuation.trace?.periods ?? {})
    .filter(([, value]) => value)
    .map(([metric, period]) => `${termLabel(metric, locale)}: ${period}`)
    .join(' · ');
  // Una valoración no publicable (estado distinto de ok, p.ej. partial por
  // entradas sin trazabilidad fechada como traceable_wacc) no puede
  // presentarse como precio objetivo: los números son una orientación del
  // motor y van degradados, con el motivo primero.
  const blockers = Array.isArray(valuation.trace?.publication_blockers)
    ? (valuation.trace?.publication_blockers as unknown[]).map(String).filter(Boolean)
    : [];
  const missingInputs = (valuation.missing_inputs ?? []).filter(Boolean);
  const engineNotice = typeof valuation.trace?.notice === 'string' ? valuation.trace.notice : null;
  const notPublishable = valuation.status !== 'ok' || valuation.publishable === false;
  const scenarioNotes = scenarioNotesList(valuation.scenario_notes);
  const reverseText = reverseDcfText(valuation.reverse_dcf);
  const assumptionsText = baseAssumptionsText(valuation.trace);
  // F348: el precio del modelo es un snapshot persistido; el precio canónico
  // (en vivo) es el de la cabecera. El del modelo se rotula con su fecha,
  // nunca como precio actual.
  const scenarios = valuationScenarioDisplay(
    {
      bear: valuation.bear_value,
      base: valuation.base_value,
      bull: valuation.bull_value,
      expected: valuation.expected_value,
    },
    valuation,
  );
  const basisLabel = scenarios.label;
  const priceAsOf = typeof valuation.trace?.price_as_of === 'string' ? valuation.trace.price_as_of : null;
  const modelPriceLabel = priceAsOf
    ? t('research.ficha.modelPriceAt', { date: formatMarketDate(priceAsOf, { day: 'numeric', month: 'short' }, undefined, locale) })
    : t('research.ficha.modelPriceNoDate');
  if (notPublishable) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label={modelPriceLabel} value={formatMoney(valuation.current_price, currency)} />
        </div>
        <div className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-4 text-sm text-amber-200">
          <p className="font-semibold">{t('research.ficha.engineGuidanceTitle')}</p>
          <p className="mt-1">
            {t('research.ficha.notPublishable', { status: label(valuation.status ?? 'unknown', locale) })}
          </p>
          {blockers.length ? <p className="mt-2 text-xs">{t('research.ficha.blockers', { list: blockers.map((id) => blockerLabel(id, locale)).join('; ') })}</p> : null}
          {missingInputs.length ? <p className="mt-2 text-xs">{t('research.ficha.missingInputs', { list: missingInputs.map((item) => termLabel(item, locale)).join(', ') })}</p> : null}
          {engineNotice ? <p className="mt-2 text-xs text-amber-200/70">{t('research.ficha.engineNote', { note: engineNotice })}</p> : null}
        </div>
        <div className="grid grid-cols-1 gap-4 opacity-60 sm:grid-cols-3">
          <Stat label={`${t('research.ficha.bearGuidance')}${basisLabel}`} value={formatMoney(scenarios.values.bear as number | null, currency)} />
          <Stat label={`${t('research.ficha.baseGuidance')}${basisLabel}`} value={formatMoney(scenarios.values.base as number | null, currency)} />
          <Stat label={`${t('research.ficha.bullGuidance')}${basisLabel}`} value={formatMoney(scenarios.values.bull as number | null, currency)} />
        </div>
        {scenarioNotes.length ? (
          <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-amber-300/80">
            {scenarioNotes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        ) : null}
        {reverseText ? <p className="text-xs leading-5 text-gray-400">{reverseText}</p> : null}
        {assumptionsText ? <p className="text-xs leading-5 text-gray-500">{assumptionsText}</p> : null}
        <p className="text-xs leading-5 text-gray-500">
          {t('research.ficha.persistedHead', { model: termLabel(valuation.model_type, locale), engine: engine ? t('research.ficha.engineSuffix', { engine }) : '', method: method ? ` · ${method}` : '', status: label(valuation.status ?? 'unknown', locale) })}{' '}
          {t('research.ficha.persistedNoteGuidance')}{' '}
          {t('research.ficha.inputPeriods', { periods: periods ? periods : NA })}
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={modelPriceLabel} value={formatMoney(valuation.current_price, currency)} />
        <Stat label={`${t('research.ficha.bear')}${basisLabel}`} value={formatMoney(scenarios.values.bear as number | null, currency)} />
        <Stat label={`${t('research.ficha.base')}${basisLabel}`} value={formatMoney(scenarios.values.base as number | null, currency)} />
        <Stat label={`${t('research.ficha.bull')}${basisLabel}`} value={formatMoney(scenarios.values.bull as number | null, currency)} />
      </div>
      {scenarioNotes.length ? (
        <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-amber-300/80">
          {scenarioNotes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      ) : null}
      {reverseText ? <p className="text-xs leading-5 text-gray-400">{reverseText}</p> : null}
      {assumptionsText ? <p className="text-xs leading-5 text-gray-500">{assumptionsText}</p> : null}
      <p className="text-xs leading-5 text-gray-500">
        {t('research.ficha.persistedHead', { model: termLabel(valuation.model_type, locale), engine: engine ? t('research.ficha.engineSuffix', { engine }) : '', method: method ? ` · ${method}` : '', status: label(valuation.status ?? 'unknown', locale) })}{' '}
        {t('research.ficha.persistedNote')}{' '}
        {t('research.ficha.inputPeriods', { periods: periods ? periods : NA })}
      </p>
    </div>
  );
}

async function MarketOpportunityView({ model, ticker }: { model: ResearchLongTermModel | null; ticker: string }) {
  const t = await getT();
  const locale = await getLocale();
  if (!model || model.status === 'not_generated') {
    return (
      <EmptyState
        action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>{t('research.ficha.marketEmptyAction')}</EmptyLink>}
        title={t('research.ficha.marketEmptyTitle')}
      />
    );
  }
  const opportunity = model.market_opportunity;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat label={t('research.ficha.tam')} value={metricValue(opportunity.top_down.tam.value, opportunity.top_down.tam.unit, t)} />
        <Stat label={t('research.ficha.sam')} value={metricValue(opportunity.top_down.sam.value, opportunity.top_down.sam.unit, t)} />
        <Stat label={t('research.ficha.som')} value={metricValue(opportunity.top_down.som.value, opportunity.top_down.som.unit, t)} />
      </div>
      <Panel title={t('research.ficha.verdictTitle')}>
        <div className="flex flex-wrap gap-2">
          <Badge>{label(opportunity.verdict.label, locale)}</Badge>
          <Badge variant="outline">{t('research.ficha.confidence', { value: label(opportunity.verdict.confidence, locale) })}</Badge>
          <Badge variant="outline">{t('research.ficha.bindingConstraint', { value: opportunity.constraints.binding_constraint ? termLabel(opportunity.constraints.binding_constraint, locale) : t('research.ficha.unknownFem') })}</Badge>
        </div>
        <p className="mt-3 text-sm text-gray-300">{opportunity.verdict.conclusion}</p>
      </Panel>
      <Panel title={t('research.ficha.bottomUpTitle')}>
        <div className="space-y-3">
          {opportunity.bottom_up.formulas.map((formula) => (
            <div className="rounded-lg border border-gray-800 p-3" key={formula.label}>
              <div className="flex justify-between gap-4 text-sm">
                <span className="text-gray-200">{formula.label}</span>
                <span className="text-teal-300">{formula.value === null ? label(formula.status, locale) : metricValue(formula.value, formula.unit ?? '', t)}</span>
              </div>
              {formula.missing_inputs?.length ? <p className="mt-2 text-xs text-amber-300">{t('research.ficha.missingInputsShort', { list: formula.missing_inputs.map((item) => termLabel(item, locale)).join(', ') })}</p> : null}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}


// Sufijos de mercados regulados UE/EEE cuya fuente primaria de fundamentales
// es ESEF (informes anuales IFRS). UK (L) queda fuera: post-Brexit no reporta
// via ESEF. Usado para ofrecer el refresh del proveedor correcto en la ficha
// (antes una empresa europea solo veia "Refrescar SEC", que siempre fallaba).
const ESEF_MARKET_SUFFIXES = new Set(['MC', 'PA', 'AS', 'BR', 'LS', 'DE', 'F', 'MI', 'VI', 'HE', 'ST', 'CO', 'OL']);

function isEsefIssuer(ticker: string): boolean {
  const idx = ticker.lastIndexOf('.');
  if (idx < 0) return false;
  return ESEF_MARKET_SUFFIXES.has(ticker.slice(idx + 1).toUpperCase());
}

// QA 18: los tickers canonicos europeos se guardan SIN sufijo (AENA, no
// AENA.MC: resolve_company quita el sufijo conocido), asi que el sufijo
// solo no basta y un emisor espanol veia los botones FMP (plan free, solo
// US) y SEC. El mercado declarado en la ficha es la senal estable.
// Mercados regulados UE/EEE cuyos emisores reportan via ESEF; Suiza y UK
// quedan fuera, como en ESEF_MARKET_SUFFIXES.
const ESEF_EXCHANGE_PATTERNS = [
  /BME|BOLSA DE MADRID/i,
  /EURONEXT/i, // cubre la nomenclatura historica «NYSE EURONEXT - ...» de Finnhub
  /XETRA|FRANKFURT|DEUTSCHE B.O.RSE/i,
  /BORSA ITALIANA|MILAN/i,
  /WIENER|VIENNA/i,
  /HELSINKI/i,
  /STOCKHOLM/i,
  /COPENHAGEN|COPENHAGUE/i,
  /OSLO/i,
  /LISBON|LISBOA/i,
  /ATHENS|ATENAS/i,
  /DUBLIN/i,
  /WARSAW|VARSOVIA/i,
  /PRAGUE|PRAGA/i,
  /BUDAPEST/i,
  /BRATISLAVA/i,
  /LJUBLJANA/i,
  /LUXEMBOURG/i,
];

function isEsefIssuerProfile(ticker: string, exchange: string | null | undefined): boolean {
  if (isEsefIssuer(ticker)) return true;
  const value = exchange?.trim();
  if (!value) return false;
  return ESEF_EXCHANGE_PATTERNS.some((pattern) => pattern.test(value));
}

/** FMP plan free solo cubre mercado US: ni sufijo de mercado ni emisor ESEF. */
function fmpCovers(ticker: string, exchange: string | null | undefined): boolean {
  return !ticker.includes('.') && !isEsefIssuerProfile(ticker, exchange);
}

/**
 * Lo que devuelve cada workspace. Derivado de las acciones con `typeof`: si el
 * contrato del backend cambia, el tipo de aquí cambia con él y el `tsc` lo
 * detecta en vez de dejarlo pasar por un `any`.
 */
type ViewWorkspaces = {
  overview: null;
  thesis: Awaited<ReturnType<typeof getThesisWithScenarios>>;
  changes: Awaited<ReturnType<typeof getResearchChangesWorkspace>>;
  financials: Awaited<ReturnType<typeof getResearchFinancialsWorkspace>>;
  model: Awaited<ReturnType<typeof getResearchLongTermModel>>;
  moat: Awaited<ReturnType<typeof getResearchMoatWorkspace>>;
  satellites: { orbits: Awaited<ReturnType<typeof getAstOrbitOverview>>; analysis: Awaited<ReturnType<typeof getAstsAnalysis>> } | null;
  peers: Awaited<ReturnType<typeof getResearchPeersWorkspace>>;
  valuation: Awaited<ReturnType<typeof getResearchValuationWorkspace>>;
  documents: Awaited<ReturnType<typeof getResearchDocumentsWorkspace>>;
  sources: Awaited<ReturnType<typeof getResearchSourceAuditsWorkspace>>;
  holders: Awaited<ReturnType<typeof getCompanyHolders>>;
  terminal: Awaited<ReturnType<typeof getFinancialTerminal>> | null;
  capital: Awaited<ReturnType<typeof getShareCapital>> | null;
  supuestos: Awaited<ReturnType<typeof getDriverAssumptions>>;
  directiva: Awaited<ReturnType<typeof getManagementCredibility>> | null;
  lecciones: Awaited<ReturnType<typeof getDecisionLessons>>;
};

/**
 * Estado vacío HONESTO de cada workspace: lo que se pinta cuando la lectura
 * degrada. Es N/D con el motivo, nunca un valor inventado, y coincide con los
 * `fallback` que las acciones ya pasaban a `getJson`.
 *
 * La clave es `keyof ViewWorkspaces`, no `View`: cuatro de los 17 módulos
 * (`terminal`, `supuestos`, `lecciones`, `directiva`) son subrutas propias y
 * nunca llegan como `?view=`, así que no tienen workspace que lanzar.
 */
const EMPTY_VIEW_DATA: { [K in keyof ViewWorkspaces]: ViewWorkspaces[K] } = {
  overview: null,
  thesis: {
    thesis: null,
    history: [],
    claims: [],
    sections: [],
    graph: null,
    redTeam: null,
    historyDetail: { count: 0, history: [] },
    partial: true,
    errors: [],
    scenarios: null,
  },
  changes: { changes: [], reviews: [], alerts: [], decisions: [], expectations: [], trades: [] },
  financials: { facts: [], calculatedMetrics: [], ttm: null },
  model: null,
  moat: null,
  satellites: null,
  peers: { comparison: null, analysis: null },
  valuation: null,
  documents: [],
  sources: [],
  holders: null,
  terminal: null,
  capital: null,
  supuestos: [],
  directiva: null,
  lecciones: { lessons: [], taxonomy: [] },
};

/**
 * Lecturas de la pestaña activa: una por cada módulo que la compone (la
 * entrada y sus secciones), lanzadas juntas al inicio del render. Cada
 * sección recoge la suya con `viewData`: la de entrada conserva el
 * comportamiento de siempre (fallo -> error boundary / BackendOffline) y el
 * resto degradan a aviso inline con reintento, nunca a vacío fingido.
 *
 * El terminal, dilución, supuestos, directiva y lecciones eran subrutas
 * propias y no tenían workspace: ahora son secciones de su pestaña.
 */
function launchTabData(
  activeView: View,
  ticker: string,
  terminalQuery: { metrics?: string; years: number; periodicity: string },
): { key: keyof ViewWorkspaces; promise: Promise<unknown> }[] {
  // Cada lectura se envuelve en su telemetría en el sitio donde se lanza
  // (guard D2a): un helper que la añadiera dentro volvería invisible el
  // rastro de cada llamada.
  const tasks: { key: keyof ViewWorkspaces; promise: Promise<unknown> }[] = [];
  switch (activeView) {
    case 'thesis':
      tasks.push({ key: 'thesis', promise: withResearchTelemetry('thesis-workspace', () => getThesisWithScenarios(ticker)) });
      break;
    case 'financials':
      tasks.push({ key: 'financials', promise: withResearchTelemetry('financials-workspace', () => getResearchFinancialsWorkspace(ticker)) });
      tasks.push({ key: 'terminal', promise: withResearchTelemetry('financial-terminal', () => getFinancialTerminal(ticker, terminalQuery)) });
      tasks.push({ key: 'capital', promise: withResearchTelemetry('share-capital', () => getShareCapital(ticker)) });
      break;
    case 'valuation':
      tasks.push({ key: 'valuation', promise: withResearchTelemetry('valuation-workspace', () => getResearchValuationWorkspace(ticker)) });
      // Modelo y oportunidad de mercado leen el mismo workspace: una lectura.
      tasks.push({ key: 'model', promise: withResearchTelemetry('long-term-model', () => getResearchLongTermModel(ticker)) });
      tasks.push({ key: 'moat', promise: withResearchTelemetry('moat-workspace', () => getResearchMoatWorkspace(ticker)) });
      tasks.push({ key: 'peers', promise: withResearchTelemetry('peers-workspace', () => getResearchPeersWorkspace(ticker)) });
      tasks.push({ key: 'supuestos', promise: withResearchTelemetry('driver-assumptions', () => getDriverAssumptions(ticker)) });
      break;
    case 'changes':
      tasks.push({ key: 'changes', promise: withResearchTelemetry('changes-workspace', () => getResearchChangesWorkspace(ticker)) });
      tasks.push({ key: 'holders', promise: withResearchTelemetry('company-holders', () => getCompanyHolders(ticker)) });
      tasks.push({ key: 'directiva', promise: withResearchTelemetry('management-credibility', () => getManagementCredibility(ticker)) });
      tasks.push({ key: 'lecciones', promise: withResearchTelemetry('decision-lessons', () => getDecisionLessons(ticker)) });
      // Solo ASTS tiene orbitales: pedirlo para otro ticker sería una
      // llamada segura de quedar sin usar.
      if (ticker === 'ASTS') {
        tasks.push({ key: 'satellites', promise: withResearchTelemetry('ast-orbits', async () => {
          const [orbits, analysis] = await Promise.all([getAstOrbitOverview().catch(() => null), getAstsAnalysis()]);
          return { orbits, analysis };
        }) });
      }
      break;
    case 'documents':
      tasks.push({ key: 'documents', promise: withResearchTelemetry('documents-workspace', () => getResearchDocumentsWorkspace(ticker, false)) });
      tasks.push({ key: 'sources', promise: withResearchTelemetry('source-audits', () => getResearchSourceAuditsWorkspace(ticker)) });
      break;
    default:
      // 'overview' no tiene workspace (el snapshot lo trae) y sus lecturas
      // (noticias, panel de vistazo) se lanzan aparte, con su degradación.
      break;
  }
  return tasks;
}

/**
 * Workspace de la sección de ENTRADA de cada pestaña: solo su caída
 * reconocida del motor degrada la página entera a BackendOffline; el resto
 * de secciones muestran un aviso inline.
 */
const ENTRY_WORKSPACE: Partial<Record<View, keyof ViewWorkspaces>> = {
  thesis: 'thesis',
  financials: 'financials',
  valuation: 'valuation',
  changes: 'changes',
  documents: 'documents',
};

export default async function ResearchCompanyPage({ params, searchParams }: PageProps) {
  const [{ ticker: rawTicker }, query] = await Promise.all([params, searchParams]);
  assertTickerShape(rawTicker);
  const t = await getT();
  const locale = await getLocale();
  const ticker = rawTicker.trim().toUpperCase();
  if (rawTicker !== ticker) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (typeof value === 'string') search.set(key, value);
    }
    redirect(`/research/${encodeURIComponent(ticker)}${search.size ? `?${search.toString()}` : ''}`);
  }
  // Las URLs antiguas de módulo o de grupo histórico (?view=moat,
  // ?view=thesis) las redirige el middleware con un 307 real, antes de
  // renderizar (ver legacyResearchRedirect). Hacerlo aquí era tarde: la
  // carcasa de loading.tsx ya iba enviada y React lo degradaba a redirección
  // de cliente, con la ficha colgada en «Cargando…» sin JS.
  const activeView = asView(query.view);
  //
  // D2a: la ficha era una cadena de `await` secuenciales. Estas lecturas NO
  // tienen dependencia de datos entre si: el snapshot no necesita el watchlist,
  // el workspace se pide por `ticker` (ya conocido) y el market no depende del
  // research. Se lanzan juntas y el coste pasa de SUMA a MAXIMO.
  //
  // Snapshot (backend) y market (Finnhub: profile+quote+candles) son
  // independientes: se lanzan juntos y el coste pasa de suma a máximo.
  // market solo se consume en 'overview'; en el resto de vistas la promesa
  // ni se crea.
  const snapshotPromise = withResearchTelemetry('company-snapshot', () => readSnapshot(ticker));
  // La cabecera muestra precio + variación + sparkline en TODAS las vistas,
  // así que market se lanza siempre; solo 'overview' lo consume en estricto
  // (BackendOffline), el resto degrada a cabecera sin cotización.
  const marketPromise = withResearchTelemetry('market-snapshot', () => getCompanyMarketSnapshot(ticker));
  // MOAT V2: solo lectura del score persistido; su fallo degrada a omitir el panel.
  const moatPromise = activeView === 'overview' ? withResearchTelemetry('moat-score', () => getMoatQualityScore(ticker)) : undefined;
  // Noticias del resumen: mismo lote con presupuesto que el resto de lecturas
  // (guard D2a). Su fallo degrada a aviso en el panel, nunca rompe la pagina.
  const newsPromise = activeView === 'overview'
    ? settleResearchBatch(
        [{ key: 'overview-news', promise: getResearchNews(null, 0, 25, ticker) }],
        RESEARCH_RENDER_BUDGET_MS,
      )
    : Promise.resolve<ResearchSettled<Awaited<ReturnType<typeof getResearchNews>>>[]>([]);
  // Noticias de la vista Noticias: mismo lote con presupuesto que el resto
  // (guard D2a). Su fallo degrada a aviso en la vista, nunca rompe la página.
  const fichaNewsPageNumber = (() => {
    const parsed = Number.parseInt(query.pagina ?? '1', 10);
    return Number.isFinite(parsed) ? Math.min(Math.max(1, parsed), 1000) : 1;
  })();
  const fichaNewsPromise = activeView === 'overview'
    ? settleResearchBatch(
        [{ key: 'ficha-news', promise: getResearchNews(null, (fichaNewsPageNumber - 1) * NEWS_PAGE_SIZE, NEWS_PAGE_SIZE + 1, ticker) }],
        RESEARCH_RENDER_BUDGET_MS,
      )
    : Promise.resolve<ResearchSettled<Awaited<ReturnType<typeof getResearchNews>>>[]>([]);
  // "Estado seguido" real del usuario. Antes esperaba al snapshot para pedirlo,
  // y no hay NINGÚN motivo: el watchlist es del tenant, no depende del ticker.
  const watchlistPromise = withResearchTelemetry('watchlist', () => getWatchlist()).catch(() => null);
  // Las lecturas de la pestaña activa también salen aquí, antes de esperar
  // el snapshot: las secciones de abajo solo las recogen. Es la fase que más
  // tiempo añadía (la tesis son 7 llamadas) y no dependía de nada anterior.
  const terminalQuery = {
    metrics: query.metrics,
    years: Math.max(1, Math.min(20, Number(query.years) || 10)),
    periodicity: ['all', 'annual', 'quarterly'].includes(query.periodicity ?? '') ? query.periodicity! : 'annual',
  };
  const viewTasks = launchTabData(activeView, ticker, terminalQuery);
  const viewPromise = viewTasks.length
    ? settleResearchBatch(viewTasks, RESEARCH_RENDER_BUDGET_MS)
    : Promise.resolve([]);
  // Panel de vistazo rápido del Resumen (opción 1, 29-oct-2026): modelo,
  // recompras y directiva vuelan con el resto; su fallo solo omite la fila
  // del panel, nunca rompe la ficha.
  const glanceModelPromise = activeView === 'overview' ? withResearchTelemetry('glance-model', () => getResearchLongTermModel(ticker)).catch(() => null) : undefined;
  const glanceCapitalPromise = activeView === 'overview' ? getShareCapital(ticker).catch(() => null) : undefined;
  const glanceCredibilityPromise = activeView === 'overview' ? getManagementCredibility(ticker).catch(() => null) : undefined;
  // En master-miss estas promesas no se consumen: el manejador se adjunta
  // EN CREACIÓN, porque un .catch posterior deja ventana de unhandledRejection
  // si rechazan durante los awaits intermedios. La propagación al consumidor
  // no cambia (el catch devuelve una promesa nueva que se descarta).
  drainRejection(marketPromise);
  drainRejection(moatPromise);
  drainRejection(newsPromise);
  drainRejection(fichaNewsPromise);
  drainRejection(viewPromise);
  let snapshot: Awaited<typeof snapshotPromise>;
  try {
    snapshot = await snapshotPromise;
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature={t('research.identity.feature', { ticker })} retryHref={`/research/${ticker}`} />;
    }
    throw error;
  }
  // Ticker con sufijo de mercado (SAN.MC) que el backend resuelve a su base
  // (SAN): misma empresa, ficha canonica unica en vez de una ficha N/D.
  const canonical = canonicalRedirectTicker(ticker, snapshot?.company.ticker);
  if (canonical) {
    redirect(`/research/${encodeURIComponent(canonical)}${query.view ? `?view=${encodeURIComponent(query.view)}` : ''}`);
  }
  if (!snapshot) {
    // F286: snapshot null tiene procedencia EXACTA: el frontend solo devuelve
    // null ante el 404 de /api/companies/{ticker}/snapshot, y ese 404 en
    // backend es «compañía ausente del master» (resolve_company). Una empresa
    // del master SIN research recibe snapshot construido y ve la guía de
    // capas faltantes con su CTA en el render normal: esta rama es solo
    // «ticker fuera del master». Política de veracidad: ninguna respuesta
    // del proveedor prueba la inexistencia del emisor buscado (un perfil {}
    // solo dice que Finnhub no conoce el símbolo) -> NUNCA 404 aquí; y un
    // perfil del ticker desnudo solo prueba que el símbolo existe en alguna
    // bolsa, no que sea ese emisor (ALM -> Almonty US, no Almirall/BME) ->
    // NUNCA CTA «Generar tesis» aquí. Tres estados honestos sin CTA.
    // Doble coincidencia SEC + proveedor (BWMX): comprobación de SOLO
    // LECTURA durante el render. Con identidad verificada se ofrece el CTA
    // explícito «Abrir ficha» (POST): crear la ficha durante un GET de
    // página crearía fichas sin acción del usuario. null = comprobación no
    // disponible: se sigue con los tres estados honestos de siempre.
    const verification = await checkCompanyIdentity(ticker);
    if (verification?.verified && !verification.already_in_master && verification.sec && verification.provider) {
      return (
        <main id="content" tabIndex={-1} className="min-h-screen bg-surface-0 text-gray-100">
          <div className="mx-auto max-w-[1600px] space-y-6">
            <Link className="inline-flex min-h-[44px] items-center text-sm text-gray-500 hover:text-gray-200 sm:min-h-0" href="/research"><ArrowLeft className="mr-2 h-4 w-4" />Research</Link>
            <EmptyState
              description={t('research.identity.verifiedDesc', { ticker, name: verification.sec.name, exchange: verification.provider.exchange, currency: verification.provider.currency ? `, ${verification.provider.currency}` : t('research.identity.currencyNa') })}
              icon={ShieldAlert}
              title={t('research.identity.verifiedTitle')}
              titleAs="h1"
              action={
                <form action={openVerifiedFicha.bind(null, ticker)}>
                  <button
                    className="inline-flex min-h-11 items-center rounded-md border border-teal-700 bg-teal-950/60 px-4 py-2 text-sm font-medium text-teal-100 transition hover:border-teal-500"
                    type="submit"
                  >
                    Abrir ficha
                  </button>
                </form>
              }
            />
          </div>
        </main>
      );
    }
    if (verification?.verified && verification.already_in_master) {
      // Carrera: la ficha se creó entre el snapshot y esta comprobación.
      redirect(`/research/${encodeURIComponent(ticker)}`);
    }
    const identity = resolveUnknownListingIdentity(await getProfile(ticker), ticker);
    const doubleCheckNote = verification
      ? t('research.identity.doubleCheckFailed')
      : '';
    const state =
      identity.kind === 'unverified'
        ? {
            title: t('research.identity.unverifiedTitle'),
            description: t('research.identity.unverifiedDesc', { ticker, providerName: identity.providerName, note: doubleCheckNote }),
          }
        : identity.kind === 'not-in-sources'
          ? {
              title: t('research.identity.notInSourcesTitle'),
              description: t('research.identity.notInSourcesDesc', { ticker }),
            }
          : {
              title: t('research.identity.uncheckedTitle'),
              description: t('research.identity.uncheckedDesc', { ticker }),
            };
    return (
      <main id="content" tabIndex={-1} className="min-h-screen bg-surface-0 text-gray-100">
        <div className="mx-auto max-w-[1600px] space-y-6">
          <Link className="inline-flex min-h-[44px] items-center text-sm text-gray-500 hover:text-gray-200 sm:min-h-0" href="/research"><ArrowLeft className="mr-2 h-4 w-4" />Research</Link>
          <EmptyState
            description={state.description}
            icon={ShieldAlert}
            title={state.title}
            titleAs="h1"
            action={
              // Siguiente paso sin CTA «Generar tesis»: buscar otra empresa o
              // volver a comprobar (recarga completa: el proveedor pudo fallar).
              <div className="flex flex-wrap items-center justify-center gap-3">
                <EmptyLink className="min-h-11 px-4 text-sm" href="/search">
                  {t('research.identity.searchOther')}
                </EmptyLink>
                <a
                  className="inline-flex min-h-11 items-center rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 transition hover:border-gray-500 hover:text-gray-100"
                  href={`/research/${encodeURIComponent(ticker)}`}
                >
                  Reintentar
                </a>
              </div>
            }
          />
        </div>
      </main>
    );
  }

  const company = snapshot.company;
  // D2a: market, watchlist y workspace de la vista vuelan juntos desde arriba.
  // Aquí ya no se encadena ninguna lectura: solo se recogen, cada una con su
  // degradación honesta.
  const [watchlist, viewSettled] = await Promise.all([watchlistPromise, viewPromise]);
  const watchlistUnknown = watchlist === null;
  // La lectura de la vista activa (una por render) que falla por caída
  // reconocida del motor (red/timeout o 5xx) degrada a BackendOffline, igual que
  // snapshot y market arriba. Cualquier otro error (4xx, auth, programación) sigue
  // relanzándose desde `viewData` al error boundary sin rebajarlo a "offline".
  const entryWorkspace = ENTRY_WORKSPACE[activeView];
  const entrySettled = entryWorkspace ? viewSettled.filter((entry) => entry.key === entryWorkspace) : [];
  const unavailableView = findUnavailableViewFailure(entrySettled, isBackendUnavailableError);
  if (unavailableView) {
    console.warn(`[research] ${ticker} · ${activeView} motor no disponible: ${unavailableView.key}=${unavailableView.reason}`);
    return <BackendOffline feature={t('research.identity.feature', { ticker })} retryHref={viewRetryHref(ticker, activeView)} />;
  }
  const isFollowed = watchlist?.some((item) => item.symbol.toUpperCase() === ticker) ?? false;
  /**
   * Dato del workspace de esta vista. Si la lectura degradó sale el estado
   * vacío HONESTO de `EMPTY_VIEW_DATA` (N/D con el motivo en el aviso), no un
   * error y no un valor inventado.
   */
  const viewData = async <K extends keyof ViewWorkspaces>(key: K): Promise<ViewWorkspaces[K]> => {
    // Un fallo o un timeout de la lectura de la vista activa NO se pinta como
    // "empresa sin datos": es indistinguible de un vacío real y esconde un
    // backend caído. Se relanza el error original (como antes del paralelismo)
    // para que lo recoja el error boundary de la ruta con su "Reintentar".
    // El estado vacío queda para lo que el backend devuelve como vacío (404).
    const failed = viewSettled.find((entry) => entry.key === key && !entry.ok);
    if (failed && !failed.ok) {
      console.warn(`[research] ${ticker} · ${activeView} falla: ${failed.key}=${failed.reason}`);
      throw failed.error instanceof Error
        ? failed.error
        : new Error(`No se pudo cargar la vista ${activeView} de ${ticker}: ${failed.reason}. Reintenta.`);
    }
    return pick(viewSettled, key, EMPTY_VIEW_DATA[key]) as ViewWorkspaces[K];
  };
  // Cabecera con cotización: si el proveedor de mercado falla fuera de
  // 'overview' la ficha sigue siendo útil; se omite el bloque, nunca se
  // fabrica un precio.
  let headerMarket: Awaited<ReturnType<typeof getCompanyMarketSnapshot>> | null = null;
  try {
    headerMarket = await marketPromise;
  } catch {
    headerMarket = null;
  }
  // La cotizacion de la cabecera se lanza YA (en cuanto se conoce el listado),
  // en paralelo al resto de lecturas de la vista, en vez de pedirse desde el
  // cliente tras hidratar. Nunca rechaza: null = el cliente la pide como antes.
  const headerQuoteSymbol = headerMarket
    ? quoteSymbolFor({ exchange: headerMarket.exchange ?? undefined, currency: headerMarket.currency ?? undefined }, headerMarket.ticker)
    : null;
  const headerQuotePromise: Promise<ExtendedQuote | null> | undefined = headerQuoteSymbol
    ? (isE2EMarketFixtureEnabled(process.env, ticker)
      ? Promise.resolve(e2eExtendedQuoteFixture(ticker) as ExtendedQuote)
      : researchRequest<ExtendedQuote>(`/api/companies/${encodeURIComponent(headerQuoteSymbol)}/extended-quote`, { timeoutMs: 6000 }).catch(() => null))
    : undefined;
  // Constructores de secciones: cada pestaña compone sus módulos como
  // secciones seguidas con título claro («Una fila, no tres menús», 29-oct-2026).
  const buildOverviewContent = async (): Promise<React.ReactNode> => {
    const t = await getT();
    // marketPromise ya se lanzó en paralelo al snapshot más arriba.
    try {
      // headerMarket ya guarda esta misma promesa resuelta (se esperó en la
      // cabecera); aquí solo se espera para distinguir la caída del motor
      // del resto de errores; el valor se lee en la cabecera.
      await marketPromise;
    } catch (error) {
      if (isBackendUnavailableError(error)) {
        return <BackendOffline feature={t('research.fichaMarketDataFeature', { ticker })} retryHref={`/research/${ticker}`} />;
      }
      throw error;
    }
    let moatScore: Awaited<ReturnType<typeof getMoatQualityScore>> = null;
    try {
      moatScore = await (moatPromise ?? getMoatQualityScore(ticker));
    } catch {
      moatScore = null;
    }
    // El resumen NO vuelve a pintar el memo de la tesis: ese documento (con su
    // debate interactivo, historial y afirmaciones) vive en `?view=thesis`.
    // Aquí solo la versión vigente, en versión corta, con salida explícita al
    // documento entero. Dos copias del mismo memo en dos URLs era lo que hacía
    // que las dos pestañas parecieran la misma.
    // Al entrar en una accion lo primero es precio (header, ya en todas
    // las vistas) y las noticias importantes: las 5 de mayor materialidad
    // entre las 25 mas recientes de la empresa, pintadas por fecha.
    const newsEntry = (await newsPromise).find((entry) => entry.key === 'overview-news');
    const overviewNewsError = !newsEntry || !newsEntry.ok;
    const overviewNews: Awaited<ReturnType<typeof getResearchNews>> = newsEntry && newsEntry.ok
      ? dedupeNewsEvents(
          newsEntry.value
            .slice()
            .sort((a, b) => (b.materiality_score ?? 0) - (a.materiality_score ?? 0))
            // Dedupe por el titular que se PINTA: dos ingestas del mismo
            // titular (sufijo de fuente o prefijo de ticker distinto en el
            // texto guardado) normalizan a claves distintas y salían
            // duplicadas seguidas (QA ASTS «Launch Delays…» x2).
            .map((event) => ({
              ...event,
              title: newsDisplayTitle(event.title, event.ticker, event.headline_from_source, event.original_headline),
            })),
        )
          .slice(0, 5)
          .sort((a, b) => b.date.localeCompare(a.date))
      : [];
    // Conexión 10b: insiders + 13F en paralelo con el PER; si falla, el panel lo dice.
    // La posición real solo se pide si la empresa está en cartera (misma lectura que Cartera).
    const [per, ownershipSignals, holdingContext] = await Promise.all([
      getCompanyPer(ticker, { exchange: company.exchange ?? undefined, currency: company.currency ?? undefined }).catch(() => ({ value: null, note: t('research.fichaPerUnavailable') })),
      getOwnershipSignals(ticker).catch(() => null),
      snapshot.in_portfolio
        ? getCompanyHolding(ticker).catch(() => ({ status: 'error' as const, message: t('research.fichaHoldingLoadError') }))
        : Promise.resolve(null),
    ]);
    // Panel de vistazo rápido: datos reales ya existentes, cada fila a su
    // sección. En móvil va arriba (bajo el precio de la cabecera); en PC
    // es la columna lateral derecha (estilo Investing, opción 1).
    const [glanceModel, glanceCapital, glanceCredibility, glanceAnalysts, glanceKeyStats] = await Promise.all([
      glanceModelPromise ?? Promise.resolve(null),
      glanceCapitalPromise ?? Promise.resolve(null),
      glanceCredibilityPromise ?? Promise.resolve(null),
      getAnalystTargets(quoteSymbolFor({ exchange: company.exchange ?? undefined, currency: company.currency ?? undefined }, ticker) ?? ticker).catch(() => null),
      getKeyStats(ticker).catch(() => null),
    ]);
    return (
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(280px,320px)]">
        <div className="min-w-0 xl:order-2">
          <QuickGlancePanel
            analysts={glanceAnalysts}
            credibility={glanceCredibility}
            currency={company.currency}
            keyStats={glanceKeyStats}
            livePrice={headerMarket?.quote?.price ?? null}
            moatScore={moatScore}
            model={glanceModel}
            shareCapital={glanceCapital}
            ticker={ticker}
          />
        </div>
        <div className="min-w-0 space-y-6 xl:order-1">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel density="compact" title={t('research.fichaLatestThesis')}>
            {snapshot.latest_thesis ? (
              <>
                <div className="flex flex-wrap gap-2">
                  {thesisIsPublic(snapshot.latest_thesis.status) && visibleThesisRating(snapshot.latest_thesis.rating, snapshot) ? <Badge>{label(snapshot.latest_thesis.rating)}</Badge> : null}
                  <Badge variant="outline">v{snapshot.latest_thesis.version}</Badge>
                  {label(snapshot.latest_thesis.status) !== label(snapshot.latest_thesis.rating) ? (
                    <Badge variant="outline">{label(snapshot.latest_thesis.status)}</Badge>
                  ) : null}
                </div>
                <ThesisSummary thesis={snapshot.latest_thesis} model={snapshot.model_summary} />
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  {/*
                      Leer la tesis es la acción principal de una ficha (por eso
                      es el único destino de primer nivel con grupo propio);
                      regenerarla es la secundaria.
                  */}
                  <Button asChild variant="outline">
                    <Link href={`/research/${encodeURIComponent(ticker)}?view=thesis`}>
                      <FileText className="mr-2 h-4 w-4" />{t('research.fichaReadFullThesis')}
                    </Link>
                  </Button>
                  <ThesisGenerateButton ticker={ticker} label={t('research.fichaRegenerateThesis')} />
                </div>
              </>
            ) : (
              <ThesisGenerateButton ticker={ticker} label={t('research.fichaGenerateFirstThesis')} emptyCopy={t('research.fichaNoThesisYet')} />
            )}
          <dl className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
            <div className="flex items-baseline gap-1.5"><dt className="text-gray-500">{t('research.fichaPerTtm')}</dt><dd className="font-semibold text-gray-100">{per.value !== null ? `${formatNumber(per.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}x` : NA}</dd></div>
            {snapshot.model_summary ? <div className="flex items-baseline gap-1.5"><dt className="text-gray-500">{t('research.fichaModel')}</dt><dd className="font-semibold text-gray-100"><Link className="inline-flex min-h-11 min-w-11 items-center underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>{snapshot.model_summary.publishable ? t('research.fichaModelPublishable') : t('research.fichaModelBlocked')}</Link></dd></div> : null}
          </dl>
          {per.note ? <p className="mt-1 text-xs text-gray-500">{per.note}</p> : null}
          </Panel>
          {/* La tarjeta compacta «Modelo fundamental a largo plazo» solo
              mostraba metadatos internos (framework, versión, motor) y el
              estado, ya presente en el chip «Modelo» de la cabecera (enlazado
              a la vista Modelo con el contenido completo). Redundante: se
              retira del overview; motor, datos y vista Modelo intactos. */}
          <CompanyPositionPanel context={holdingContext} />
        </div>
        <Panel collapsible="mobile"
          actions={
            <Link
              className="inline-flex min-h-[44px] items-center sm:min-h-0 text-sm text-teal-300 hover:text-teal-200"
              href="#noticias"
            >
              {t('research.fichaViewAll')}
            </Link>
          }
          description={t('research.fichaLatestNewsDesc')}
          title={t('research.fichaLatestNews')}
        >
          {overviewNewsError ? (
            <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
              {t('research.fichaNewsLoadError')}
            </p>
          ) : overviewNews.length === 0 ? (
            <EmptyState title={t('research.fichaNoRecentNews')} />
          ) : (
            <ul className="space-y-3">
              {overviewNews.map((event) => (
                <li className="text-sm" key={event.id}>
                  <NewsHeadline event={event} />
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                    <ImpactBadge direction={event.impact_direction} />
                    <span>{event.source} · {newsDateLabel(event, t, locale)}</span>
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        {/*
            Los cambios recientes vienen en el snapshot y no se pintaban en
            ninguna vista: son la respuesta a "¿esto sigue valiendo lo que
            valía la última vez?".
        */}
        <Panel collapsible="mobile"
          actions={
            <Link
              className="inline-flex min-h-[44px] sm:min-h-0 items-center text-sm text-teal-300 hover:text-teal-200"
              href={`/research/${encodeURIComponent(ticker)}?view=seguimiento`}
            >
              {t('research.fichaViewAllChanges')}
            </Link>
          }
          density="compact"
          title={t('research.fichaLatestChanges')}
        >
          {snapshot.recent_changes?.length ? (
            <ul className="space-y-2">
              {snapshot.recent_changes.slice(0, 3).map((change) => (
                <li className="min-w-0 rounded-lg border border-gray-800/70 bg-black/20 p-3 text-sm text-gray-300" key={change.id}>
                  <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                    <Badge variant="outline">{label(change.impact_direction)}</Badge>
                    <span className="text-xs text-gray-500">
                      {t('research.fichaMaterialityScore', { score: change.materiality_score })} · {formatDate(change.created_at)}
                    </span>
                  </div>
                  <p className="break-words leading-6 [overflow-wrap:anywhere]">{changeSummaryText(change.summary)}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-500">{t('research.fichaNoChangesSinceReview')}</p>
          )}
        </Panel>
        {snapshot.research_health.missing?.length ? (
          <MobileCollapse title={t('research.fichaMissingLayersTitle', { count: snapshot.research_health.missing.length })}>
          <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200">
            <p>{t('research.fichaMissingLayersHeading')}</p>
            <ul className="mt-2 space-y-1">
              {snapshot.research_health.missing.map((layer) => {
                const action = missingLayerAction(ticker, layer);
                return (
                  <li key={layer}>
                    {missingLayerLabel(layer)}
                    {action ? (
                      <>
                        {' — '}
                        <Link className="underline hover:text-amber-100" href={action.href}>
                          {action.label}
                        </Link>
                      </>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
          </MobileCollapse>
        ) : null}
        <Panel collapsible="mobile"
          actions={moatScore ? (
            <Link
              className="inline-flex min-h-11 min-w-11 items-center text-sm text-teal-300 hover:text-teal-200"
              href={`/research/${encodeURIComponent(ticker)}?view=valoracion#foso`}
            >
              {t('research.fichaViewMoatEval')}
            </Link>
          ) : undefined}
          title={t('research.fichaFinancialQuality')}
        >
          {moatScore ? (
            <MoatPanel company={company} metric={moatScore} ti={t} fmt={createFormatters(locale)} />
          ) : (
            <EmptyState title={t('research.fichaNoQualityEval')} />
          )}
        </Panel>
        {/*
            Los cuatro saltos que se piden antes que nada al abrir una ficha.
            Están aquí, en el resumen, y no repartidos por las 16 píldoras
            planas que había antes.
        */}
        <Panel className="hidden md:block" collapsible="mobile"
          description={t('research.fichaWhereNextDesc')}
          density="compact"
          title={t('research.fichaWhereNext')}
        >
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
            {[
              [t('research.fichaNextModel'), 'valoracion#modelo'],
              [t('research.fichaNextOpportunity'), 'valoracion#oportunidad'],
              [t('research.fichaNextPeers'), 'valoracion#comparables'],
              [t('research.fichaNextDocs'), 'fuentes#documentos'],
            ].map(([nextLabel, nextView]) => (
              <NextStepLink href={`/research/${encodeURIComponent(ticker)}?view=${nextView}`} key={nextView}>
                {nextLabel}
              </NextStepLink>
            ))}
          </div>
        </Panel>
        <OwnershipSignalsPanel signals={ownershipSignals} ticker={ticker} />
        {ticker === 'ASTS' ? <Panel collapsible="mobile" title={t('research.fichaSatellitesPanel')}><Link className="mt-2 inline-block text-sm text-teal-300" href={`/research/${encodeURIComponent(ticker)}?view=seguimiento#satellites`}>{t('research.fichaOrbitalSignal')}</Link></Panel> : null}
        <p role="status" className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200">
          {researchValuability(snapshot)}
        </p>
        {/* Price chart lives once in the company header, across all views. */}
        </div>
      </div>
    );
  };

  const buildNoticiasSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    // Noticias de la empresa dentro de su ficha (cohesión: sin salir a
    // /research/news). Mismo componente y misma paginación que la portada de
    // noticias, filtrado por ticker en la API. La lectura sale del lote con
    // presupuesto lanzado arriba; su fallo degrada a aviso, nunca tumba la ficha.
    const newsPage = fichaNewsPageNumber;
    const tickerContext = await getTickerContext().catch(() => ({ portfolioTickers: [] as string[], watchlistTickers: [] as string[] }));
    const fichaNewsEntry = (await fichaNewsPromise).find((entry) => entry.key === 'ficha-news');
    const fichaNewsError = !fichaNewsEntry || !fichaNewsEntry.ok;
    const fetchedNews: Awaited<ReturnType<typeof getResearchNews>> = fichaNewsEntry && fichaNewsEntry.ok ? fichaNewsEntry.value : [];
    const newsHasMore = fetchedNews.length > NEWS_PAGE_SIZE;
    const newsEvents = dedupeNewsEvents(fetchedNews.slice(0, NEWS_PAGE_SIZE));
    // El flujo ya trae su propia sección con cabecera; sin Panel extra.
    return fichaNewsError ? (
      <Panel title={t('research.fichaCompanyNews')}>
        <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
          {t('research.fichaNewsLoadError')}
        </p>
      </Panel>
    ) : (
      <NewsEventsFlow
        events={newsEvents}
        hasMore={newsHasMore}
        inFicha
        key={`ficha-noticias-${ticker}-${newsPage}`}
        lane={null}
        page={newsPage}
        ticker={ticker}
        portfolioTickers={tickerContext.portfolioTickers}
        watchlistTickers={tickerContext.watchlistTickers}
      />
    );
  };

  const buildThesisContent = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const data = await viewData('thesis');
    return (
      <div className="min-w-0 max-w-full space-y-6 [overflow-wrap:anywhere]">
        <div className="flex flex-wrap items-center gap-3">
          <ThesisGenerateButton ticker={ticker} />
          <ThesisApproveButton
            ticker={ticker}
            disabled={data.history.length === 0}
            latestStatus={data.thesis?.status ?? null}
            latestVersion={data.thesis?.version ?? null}
            riskNotes={[
              ...(snapshot?.model_summary && !snapshot.model_summary.publishable ? [t('research.fichaRiskPartialValuation')] : []),
              ...((data.thesis?.missing_inputs?.length ?? 0) > 0 ? [t('research.fichaRiskMissingInputs', { count: data.thesis?.missing_inputs?.length ?? 0 })] : []),
              ...(typeof data.thesis?.red_team_score === 'number' && data.thesis.red_team_score < 40 ? [t('research.fichaRiskRedTeam', { score: data.thesis.red_team_score })] : []),
            ]}
            olderPublishedVersion={
              data.historyDetail.history
                .filter((entry) => entry.status === 'published' && entry.version !== data.thesis?.version)
                .map((entry) => entry.version)
                .reduce<number | null>((a, b) => (a === null ? b : Math.max(a, b)), null)
            }
          />
          <ThesisExportMenu
            hasPublished={data.historyDetail.history.some((entry) => entry.status === 'published')}
            latestDraftVersion={data.historyDetail.history.filter((entry) => entry.status !== 'published').map((entry) => entry.version).reduce((a, b) => Math.max(a, b), 0) || null}
            ticker={ticker}
          />
          <Badge variant="outline">{t('research.fichaVersionsCount', { count: data.history.length })}</Badge>
          <Badge variant="outline">{t('research.fichaClaimsCount', { count: data.claims.length })}</Badge>
        </div>
        <Panel title={t('research.fichaVersionHistory')} collapsible="mobile">
          {data.historyDetail.history.length === 0 ? (
            <EmptyState title={t('research.fichaNoVersionHistory')} />
          ) : (
            <PagedList
              className="space-y-3"
              items={collapseVersionHistory(data.historyDetail.history).map((group) => {
                const entry = group[0];
                return {
                  key: `history-${entry.id}`,
                  node: (
                    <div className="rounded-lg border border-gray-800 p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">v{entry.version}</Badge>
                        {group.length > 1 ? (
                          <Badge variant="outline">{t('research.fichaSameSummaryVersions', { count: group.length, from: entry.version, to: group[group.length - 1].version })}</Badge>
                        ) : null}
                        {versionHistoryBadges(entry, label).map((badge) => (
                          <Badge
                            key={badge.key}
                            variant={
                              badge.key === 'rating-change'
                                || (badge.key === 'status' && entry.status === 'published')
                                ? 'default'
                                : 'outline'
                            }
                          >
                            {badge.text}
                          </Badge>
                        ))}
                        <span className="ml-auto text-xs text-gray-500">
                          {formatUserDateTime(entry.updated_at)}
                        </span>
                      </div>
                      {entry.diff ? (
                        <p className="mt-2 text-sm leading-6 text-gray-400">{entry.diff.change_summary}</p>
                      ) : (
                        <p className="mt-2 text-xs text-gray-500">{t('research.fichaFirstVersionNoDiff')}</p>
                      )}
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                        <span>{t('research.fichaRedTeamScore', { score: entry.red_team_score })}</span>
                        <span>{t('research.fichaDataConfidence', { score: entry.data_confidence_score })}</span>
                      </div>
                    </div>
                  ),
                };
              })}
              label={t('research.fichaVersionHistory')}
              pageSize={10}
            />
          )}
          <p className="mt-3 text-xs text-gray-500">
            {t('research.fichaHistoryFootnote')}
          </p>
        </Panel>
        <ThesisAudioPlayer
          ticker={ticker}
          version={data.historyDetail.history.filter((entry) => entry.status === 'published').reduce<number | null>((a, entry) => (a === null ? entry.version : Math.max(a, entry.version)), null)}
        />
        <div id="tesis-actual" style={{ scrollMarginTop: '5rem' }}>
        <Panel title={t('research.fichaCurrentThesis')}>
          {data.thesis ? (
            <ThesisMemo
              thesis={data.thesis}
              ticker={ticker}
              locale={locale}
              currency={company.currency}
              model={snapshot?.model_summary}
              extraSections={data.sections.filter((section) => section.section_key !== 'thesis_debate')}
              debateBody={
                data.sections.find((section) => section.section_key === 'thesis_debate')?.body ?? null
              }
            />
          ) : (
            <EmptyState
              action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=fuentes`}>{t('research.fichaImportSourcesFirst')}</EmptyLink>}
              title={t('research.fichaNoThesis')}
            />
          )}
        </Panel>
        </div>
        <ThesisScenariosPanel adrRatio={data.thesis?.valuation_basis?.adr_ratio} currency={company.currency} data={data.scenarios} />
        <Panel title={t('research.fichaClaimsEvidence')}>
          <ResearchClaimForm action={createResearchClaim.bind(null, ticker)} />
          <div className="space-y-3">
            {data.claims.length ? groupClaimsByVersion(data.claims, data.history).map((group) => (
              <details key={group.key} open={group.claims.some((claim) => claim.thesis_version_id === data.thesis?.id)} className="rounded-lg border border-gray-800 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-gray-300">{t('research.fichaGroupClaims', { label: group.label, count: group.claims.length })}</summary>
                <PagedList
                  className="mt-3"
                  items={group.claims.map((claim) => ({
                    key: `claim-${claim.id}`,
                    node: (
                      <div className="rounded-lg border border-gray-800 p-4">
                        <div className="flex flex-wrap gap-2"><Badge variant="outline">{label(claim.status)}</Badge><Badge variant="outline">{t('research.fichaMaterialityLower', { score: claim.materiality_score })}</Badge><Badge variant="outline">{t('research.fichaEvidenceCount', { count: claim.evidence.length })}</Badge></div>
                        <p className="mt-3 text-sm text-gray-300">{claim.statement}</p>
                      </div>
                    ),
                  }))}
                  label={t('research.fichaClaimsOf', { label: group.label })}
                  pageSize={10}
                />
              </details>
            )) : (
              <EmptyState
                action={<EmptyLink href="#statement">{t('research.fichaWriteFirstClaim')}</EmptyLink>}
                title={t('research.fichaNoClaims')}
              />
            )}
          </div>
        </Panel>
      </div>
    );
  };

  const buildChangesContent = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const locale = await getLocale();
    const data = await viewData('changes');
    // Contexto de guía (revisiones anclables + noticias atribuidas): opcional,
    // su fallo no puede romper la pestaña Seguir.
    // Operaciones simuladas de la empresa: mismo carácter opcional que la guía.
    const [guideContext, paperTrades] = await Promise.all([
      getGuideContext(ticker).catch(() => null),
      getCompanyPaperTrades(ticker).catch(() => null),
    ]);
    return (
      <div className="space-y-6">
        {data.changes.length || data.reviews.length || data.alerts.length ? (
          <ChangesFeed alerts={data.alerts} changes={data.changes} reviews={data.reviews} ticker={ticker} />
        ) : (
          <Panel title={t('research.fichaWhatChanged')}>
            <EmptyState
              action={<EmptyLink href="/research/news">{t('research.fichaAnalyzeLatestNews')}</EmptyLink>}
              title={t('research.fichaNoMaterialChanges')}
            />
          </Panel>
        )}
        <GuideContextPanel ticker={ticker} context={guideContext} hideReviews />
        <DecisionAndRealityPanel ticker={ticker} decisions={data.decisions} reviews={data.expectations} trades={data.trades} t={t} locale={locale} />
        <CompanyPaperTrades locale={locale} state={paperTrades} ticker={ticker} />
      </div>
    );
  };

  const buildHoldersSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const holders = await viewData('holders');
    // Propietarios = 13F (gestores) + insiders (Form 4, SEC EDGAR, gratis).
    // Los Form 4 persistidos se leen del backend; sin red ni proveedor de
    // pago. Best-effort: cualquier fallo degrada a panel vacio honesto.
    const [insiderFilings, participation] = await Promise.all([
      getInsiderFilings(ticker, 8).catch(() => null),
      getParticipationFilings(ticker).catch(() => null),
    ]);
    return (
      <div className="space-y-6">
        <ParticipationFilingsPanel data={participation} />
        {holders === null ? (
          <EmptyState title={t('research.fichaHoldersLoadError')} />
        ) : holders.status === 'sin_identificador' ? (
          <EmptyState title={holders.identity_source ?? t('research.fichaNoCusipIdentity')} />
        ) : holders.status === 'sin_datos' ? (
          <EmptyState title={t('research.fichaNo13fSynced')} />
        ) : (
          <Panel title={t('research.fichaHoldersPanel')}>
            {holders.holders.length ? (
              <ul className="space-y-3">
                {holders.holders.map((holder) => (
                  <li className="rounded-lg border border-gray-800 p-3 text-sm" key={holder.slug}>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <Link className="font-medium text-teal-300 hover:text-teal-200" href={`/inversores/${holder.slug}`}>{holder.name}</Link>
                      <span className="text-gray-200">{holder.value_usd !== null ? formatMarketCapUsd(holder.value_usd) : NA}</span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {t('research.fichaPortfolioAt', { date: holder.report_date ? formatDate(holder.report_date) : t('research.fichaUnknownDate') })}
                      {holder.coverage === 'partial' ? ` · ${t('research.fichaPartialData')}` : ''}
                      {holder.filing_url ? (
                        <>
                          {' · '}
                          <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={holder.filing_url} rel="noopener noreferrer" target="_blank">{t('research.fichaOriginal13f')}</a>
                        </>
                      ) : null}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title={t('research.fichaNoManagerDeclares')} />
            )}
            <p className="mt-4 text-xs text-gray-500">
              {t('research.fichaManagersSummary', { withData: holders.managers_with_data, withoutData: holders.managers_without_data })}
              {holders.managers_partial ? t('research.fichaManagersPartialSuffix', { count: holders.managers_partial }) : ''} · {ownershipLimitations(holders.limitations)}
            </p>
          </Panel>
        )}
        <Panel title={t('research.fichaInsidersPanel')}>
          {insiderFilings === null || insiderFilings.status !== 'ok' || insiderFilings.filings.length === 0 ? (
            insiderFilings?.foreign_issuer ? (
              <EmptyState
                description={t('research.fichaForeignIssuerDesc')}
                title={t('research.fichaForeignIssuerTitle')}
              />
            ) : (
              <EmptyState title={t('research.fichaNoInsiderTrades')} />
            )
          ) : (
            <ul className="space-y-3">
              {insiderFilings.filings.map((filing) => (
                <li className="rounded-lg border border-gray-800 p-3 text-sm" key={filing.accession_number}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-gray-300">
                      {filing.form}{filing.is_amendment ? t('research.fichaAmendmentSuffix') : ''} · {filing.filing_date ? formatDate(filing.filing_date) : t('research.fichaUnknownDate')}
                    </span>
                    {safeHttpUrl(filing.source_url) ? (
                      <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={safeHttpUrl(filing.source_url) ?? undefined} rel="noopener noreferrer" target="_blank">{t('research.fichaOriginalForm4')}</a>
                    ) : null}
                  </div>
                  <ul className="mt-2 space-y-1 text-xs text-gray-400">
                    {filing.transactions.slice(0, 6).map((tx, index) => (
                      <li key={`${filing.accession_number}-${index}`}>
                        {insiderName(tx.insider)} · {insiderRole(tx.role, tx.officer_title)} · {tx.code === 'P' ? t('research.fichaTxBuy') : tx.code === 'S' ? t('research.fichaTxSell') : tx.code ?? '—'}
                        {typeof tx.shares === 'number' ? t('research.fichaTxSharesSuffix', { count: formatNumber(tx.shares) }) : ''}
                        {typeof tx.value === 'number' && Number.isFinite(tx.value) ? ` · ${tx.currency && isValidCurrencyCode(tx.currency) ? formatPrice(tx.value, tx.currency, { minimumFractionDigits: 0, maximumFractionDigits: 0 }) : formatNumber(tx.value, { maximumFractionDigits: 0 })}` : ''}
                        {tx.currency == null && typeof tx.value === 'number' ? t('research.fichaTxNoCurrencySuffix') : ''}
                        {tx.tx_date ? ` · ${formatDate(tx.tx_date)}` : ''}
                      </li>
                    ))}
                  </ul>
                  {filing.transactions.length > 6 ? (
                    <p className="mt-1 text-xs text-gray-500">{t('research.fichaTxShown', { total: formatNumber(filing.transactions.length, { maximumFractionDigits: 0 }) })}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    );
  };

  const buildFinancialsContent = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const data = await viewData('financials');
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap gap-3">
          {/* FMP plan free solo cubre mercado US (402 en el resto): el boton
              solo se ofrece cuando el emisor entra en esa cobertura (B30).
              La decision usa el perfil (mercado declarado), no solo el
              sufijo del ticker: los europeos canonicos no lo llevan (AENA). */}
          {fmpCovers(ticker, company.exchange) ? (
            <MutationForm action={refreshCompanyFinancials.bind(null, ticker)} successMessage={t('research.fichaFinancialsUpdatedFmp')}><Button type="submit" variant="outline">{t('research.fichaRefreshFinancialsFmp')}</Button></MutationForm>
          ) : null}
          {isEsefIssuerProfile(ticker, company.exchange) ? (
            <MutationForm action={refreshCompanyFinancialsESEF.bind(null, ticker)} successMessage={t('research.fichaFinancialsUpdatedEsef')}><Button type="submit" variant="outline">{t('research.fichaRefreshEsef')}</Button></MutationForm>
          ) : (
            <MutationForm action={refreshCompanyFinancialsSEC.bind(null, ticker)} successMessage={t('research.fichaFinancialsUpdatedSec')}><Button type="submit" variant="outline">{t('research.fichaRefreshSec')}</Button></MutationForm>
          )}
          <MutationForm action={refreshCompanyResearchModel.bind(null, ticker)} successMessage={t('research.fichaModelMetricsRefreshed')}><Button type="submit"><RefreshCcw className="mr-2 h-4 w-4" />{t('research.fichaRecalculate')}</Button></MutationForm>
        </div>
        <Panel title={t('research.fichaCurrentFundamentals')}><TtmPanel ttm={data.ttm} /></Panel>
        <Panel title={t('research.fichaTraceableMetrics')}><MetricsGrid metrics={data.calculatedMetrics} /></Panel>
        <Panel title={t('research.fichaCanonicalFacts')}><FactTable ticker={ticker} facts={data.facts} refreshLabel={
            fmpCovers(ticker, company.exchange)
              ? t('research.fichaRefreshFinancialsFmp')
              : isEsefIssuerProfile(ticker, company.exchange)
                ? t('research.fichaRefreshEsef')
                : t('research.fichaRefreshSec')
          } /></Panel>
      </div>
    );
  };

  const buildModelSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const locale = await getLocale();
    const model = await viewData('model');
    return (
      <div className="space-y-5">
        <MutationForm action={refreshCompanyResearchModel.bind(null, ticker)} successMessage={t('research.fichaModelGenerated')}><Button type="submit"><RefreshCcw className="mr-2 h-4 w-4" />{t('research.fichaGenerateModel')}</Button></MutationForm>
        <LongTermModelPanel model={model?.status === 'not_generated' ? null : model} ticker={ticker} t={t} locale={locale} />
      </div>
    );
  };

  const buildMarketOpportunitySection = async (): Promise<React.ReactNode> => {
    return <MarketOpportunityView model={await viewData('model')} ticker={ticker} />;
  };

  const buildMoatSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const moat = await viewData('moat');
    return (
      <div className="space-y-5">
        <MutationForm action={refreshCompanyResearchModel.bind(null, ticker)} successMessage={t('research.fichaMoatRefreshed')}><Button type="submit" variant="outline"><ShieldCheck className="mr-2 h-4 w-4" />{t('research.fichaReevaluateEvidence')}</Button></MutationForm>
        <MoatClassificationPanel moat={moat} ti={t} />
        <MoatChecklistPanel moat={moat} ti={t} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {moat?.moats.length ? moat.moats.map((item) => {
            const definition = moatDefinition(item.type);
            return (
              <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={item.type}>
                <div className="flex justify-between gap-3"><MoatTerm type={item.type} /><Badge>{item.strength}/100</Badge></div>
                <p className="mt-3 text-sm text-gray-400">{label(item.status)} · {label(item.trend)} · {t('research.fichaPersistence')} {label(item.persistence)}</p>
                {definition ? <p className="mt-2 text-xs leading-5 text-gray-500">{definition}</p> : null}
                <p className="mt-2 text-xs text-gray-500">{t('research.fichaMoatClaims', { forCount: item.supporting_claim_ids.length, againstCount: item.contradicting_claim_ids.length })}</p>
              </div>
            );
          }) : (
            <EmptyState
              action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>{t('research.fichaGenerateModelReevaluate')}</EmptyLink>}
              title={t('research.fichaNoMoatEval')}
            />
          )}
        </div>
      </div>
    );
  };

  const buildSatellitesSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    // El panel ya degrada solo cuando no hay datos; aquí la lectura llega del
    // lote en paralelo (null si degradó, igual que antes).
    const satellites = ticker === 'ASTS' ? await viewData('satellites') : null;
    return ticker === 'ASTS' ? <AstOrbitPanel analysis={satellites?.analysis ?? null} data={satellites?.orbits ?? null} locale={locale} /> : <EmptyState title={t('research.fichaOrbitalOnlyAsts')} />;
  };

  const buildPeersSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const peers = await viewData('peers');
    return (
      <div className="space-y-6">
        <Panel title={t('research.fichaPeerSet')}><p className="text-sm text-gray-300">{peers.comparison?.basis ? (PEERS_BASIS_KEYS[peers.comparison.basis] ? t(PEERS_BASIS_KEYS[peers.comparison.basis]) : peers.comparison.basis) : t('research.fichaNoPeerSet')} · {t('research.fichaPeersWithData', { count: peers.comparison?.peer_count ?? 0 })}{(peers.comparison?.peers_without_data ?? []).length > 0 ? t('research.fichaPeersWithoutDataSuffix', { list: (peers.comparison?.peers_without_data ?? []).join(', ') }) : ''}</p><div className="mt-4 flex flex-wrap gap-2">{peers.comparison?.companies.map((peer) => <Badge variant={peer.is_target ? 'default' : 'outline'} key={peer.ticker}>{peer.ticker}</Badge>)}</div></Panel>
        <Panel title={t('research.fichaPeerMetrics')}><div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{Object.entries(peers.comparison?.benchmarks ?? {}).map(([metric, value]) => <div className="rounded-lg border border-gray-800 p-3" key={metric}><div className="text-sm text-gray-200">{metric}</div><div className="mt-2 text-xs text-gray-500">{t('research.fichaPeerTarget', { value: formatPeerValue(value.target_value, metric) })}{value.target_atypical ? t('research.fichaAtypicalSuffix') : ''}{t('research.fichaMedianSuffix', { value: peerMedianText(value, metric) })}{t('research.fichaSampleSuffix', { count: value.peer_sample_size })}</div>{(value.excluded_atypical ?? []).length > 0 ? <div className="mt-1 text-xs text-amber-300/80">{t('research.fichaOutsideMedian', { list: (value.excluded_atypical ?? []).map((ex) => `${ex.ticker} ${ex.value ?? t('research.fichaNoDataShort')}`).join(', ') })}</div> : null}</div>)}</div></Panel>
        <Panel title={t('research.fichaAdvantages')}><p className="text-sm text-gray-400">{peers.analysis?.methodology ? (PEERS_METHODOLOGY_KEYS[peers.analysis.methodology] ? t(PEERS_METHODOLOGY_KEYS[peers.analysis.methodology]) : peers.analysis.methodology) : t('research.fichaNoPeerAnalysis')}</p><p className="mt-3 text-xs text-amber-300">{peers.analysis?.insufficient_data.join(', ')}</p></Panel>
      </div>
    );
  };

  const buildValuationContent = async (): Promise<React.ReactNode> => {
    return <ValuationView valuation={await viewData('valuation')} currency={company.currency} ticker={ticker} />;
  };

  const buildDocumentsContent = async (): Promise<React.ReactNode> => {
    const t = await getT();
    // Conexión 10a: las lecturas de la biblioteca enlazadas a este ticker se
    // piden en paralelo; si la biblioteca falla, la vista sigue sin ellas.
    const [documents, libraryReadings] = await Promise.all([
      viewData('documents'),
      getKnowledgeDocumentsForTicker(ticker).catch(() => null),
    ]);
    return (
      <div className="space-y-6">
        <details className="rounded-lg border border-gray-800 bg-surface-1 p-4" data-testid="add-source">
          <summary className="flex min-h-11 cursor-pointer items-center text-sm font-medium text-teal-300">{t('research.fichaAddSource')}</summary>
          <div className="mt-4">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel title={t('research.fichaUploadPrimarySource')}><MutationForm action={importResearchDocumentFile} className="grid grid-cols-1 gap-3" successMessage={t('research.fichaDocUploaded')}><input type="hidden" name="ticker" value={ticker} /><Input name="title" placeholder={t('research.fichaDocTitlePh')} required /><FileUploadInput name="file" required /><Button type="submit">{t('research.fichaUpload')}</Button></MutationForm></Panel>
          <Panel title={t('research.fichaImportFromUrl')}><MutationForm action={importResearchDocumentUrl} className="grid grid-cols-1 gap-3" successMessage={t('research.fichaDocImported')}><input type="hidden" name="ticker" value={ticker} /><Input name="title" placeholder={t('research.fichaDocTitlePh')} required /><Input name="url" type="url" placeholder="https://..." required /><Input name="source_type" placeholder="sec_filing / investor_relations" defaultValue="url" /><Button type="submit">{t('research.fichaImport')}</Button></MutationForm></Panel>
        </div>
          </div>
        </details>
        {/* F249: las fichas enlazan a la fuente primaria cuando el
            documento tiene source_url (filings SEC la traen); sin URL la
            ficha queda como texto, nunca un enlace roto. */}
        <Panel title={t('research.fichaDocuments')} actions={<Link className="text-sm text-teal-300" href={`/research/${encodeURIComponent(ticker)}/filings`}>{t('research.fichaYearOverYearReport')}</Link>}>
          {documents.length ? (
            <DocumentsList
              documents={documents.map((document) => ({
                id: document.id,
                title: document.title,
                url: safeHttpUrl(document.source_url),
                tier: etiquetaTierFuente(document.source_tier),
                tierRank: tierRankFuente(document.source_tier),
                type: label(document.source_type),
                published: document.published_at ? formatDate(document.published_at) : t('research.fichaUnknownDate'),
                publishedTs: document.published_at ?? null,
              }))}
            />
          ) : (
            <EmptyState
              action={<EmptyLink href="/research/sources">{t('research.fichaImportFirstDoc')}</EmptyLink>}
              title={t('research.fichaNoDocsIngested')}
            />
          )}
        </Panel>
        <Panel title={t('research.fichaLibraryReadings')} actions={<Link className="text-sm text-teal-300" href="/knowledge?tab=subir">{t('research.fichaAddToLibrary')}</Link>}>
          {libraryReadings === null ? (
            <EmptyState title={t('research.fichaLibraryLoadError')} />
          ) : libraryReadings.length ? (
            <ul className="space-y-3">
              {libraryReadings.map((reading) => (
                <li className="rounded-lg border border-gray-800 p-4" key={reading.id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <FileText className="h-4 w-4 text-teal-300" />
                    <Link className="font-medium text-gray-200 underline decoration-gray-700 underline-offset-4 transition hover:text-teal-200" href={libraryDocumentHref(reading.id)}>{reading.title}</Link>
                  </div>
                  <p className="mt-2 text-xs text-gray-500">{reading.author ?? t('research.fichaUnknownAuthor')}{reading.publication_date ? ` · ${formatDate(reading.publication_date)}` : ''}</p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              action={<EmptyLink href="/knowledge">{t('research.fichaAssignTickerToDoc')}</EmptyLink>}
              title={t('research.fichaNoLibraryLink', { ticker })}
            />
          )}
        </Panel>
      </div>
    );
  };

  const buildSourcesSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    const audits = await viewData('sources');
    return (
      <Panel title={t('research.fichaSourceAudits')}>
        {audits.length ? (
          <div className="space-y-3">
            {audits.length > 100 ? <p className="text-xs text-gray-500">{t('research.fichaAuditsShown', { total: formatNumber(audits.length, { maximumFractionDigits: 0 }) })}</p> : null}
            {/* Solo la auditoría más reciente a la vista; el historial de
                versiones viejas queda plegado (era un muro de tarjetas casi
                idénticas que se leía como bug). */}
            {(() => {
              const ordered = sortAuditsRecentFirst(audits);
              const renderAudit = (audit: (typeof ordered)[number]) => <div className="rounded-lg border border-gray-800 p-4" key={audit.id}><div className="flex flex-wrap gap-2"><Badge>{auditStatusLabel(audit.passed, locale)}</Badge><Badge variant="outline">{auditScoreText(audit.passed, audit.source_coverage_score, String, locale)}</Badge><Badge variant="outline">{audit.thesis_version != null ? t('research.fichaThesisVersionShort', { version: audit.thesis_version }) : t('research.fichaThesisVersionMissing')}</Badge></div><SourceAuditDetail audit={audit} ticker={ticker} locale={locale} /></div>;
              const previous = ordered.slice(1, 100);
              return <>
                {renderAudit(ordered[0])}
                {previous.length ? (
                  <details className="rounded-lg border border-gray-800 p-4">
                    <summary className="flex min-h-11 cursor-pointer items-center text-sm font-medium text-gray-400">{formatNumber(previous.length, { maximumFractionDigits: 0 })} {previous.length === 1 ? t('research.fichaAuditPreviousSingular') : t('research.fichaAuditPreviousPlural')} {t('research.fichaAuditsOldVersions')}</summary>
                    <div className="mt-3 space-y-3">{previous.map(renderAudit)}</div>
                  </details>
                ) : null}
              </>;
            })()}
          </div>
        ) : (
          <EmptyState
            action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=thesis`}>{t('research.fichaGenerateThesisForAudit')}</EmptyLink>}
            title={t('research.fichaNoSourceAudits')}
          />
        )}
      </Panel>
    );
  };

  const buildChatSection = async (): Promise<React.ReactNode> => {
    const t = await getT();
    return (
      <div className="space-y-6" id="chat-empresa" style={{ scrollMarginTop: '1rem' }}>
        <LegacyChatRedirect ticker={ticker} question={query.chat} />
        <Panel title={t('research.fichaAskBrain')}>
          {/* Sin chat propio: los atajos y el campo abren el Cerebro (panel
              global) con el ticker puesto, con su contexto de página e historial. */}
          <ChatIntentLinks ticker={ticker} />
          <BrainAskForm ticker={ticker} />
        </Panel>
      </div>
    );
  };

  // Secciones que eran subrutas propias hasta el 29-oct-2026.
  const buildTerminalSection = async (): Promise<React.ReactNode> => {
    const terminal = await viewData('terminal');
    if (!terminal) return <EmptyState title={t('research.fichaTerminalEmpty')} />;
    return <FinancialTerminalSection locale={locale} metrics={terminalQuery.metrics} periodicity={terminalQuery.periodicity} terminal={terminal} years={terminalQuery.years} />;
  };
  const buildCapitalSection = async (): Promise<React.ReactNode> => <ShareCapitalSection data={await viewData('capital')} locale={locale} ticker={ticker} />;
  const buildSupuestosSection = async (): Promise<React.ReactNode> => <DriverAssumptionsSection assumptions={await viewData('supuestos')} locale={locale} ticker={ticker} />;
  const buildDirectivaSection = async (): Promise<React.ReactNode> => {
    const dashboard = await viewData('directiva');
    if (!dashboard) return <EmptyState title={t('research.fichaDirectivaEmpty')} />;
    return <ManagementCredibilitySection dashboard={dashboard} locale={locale} ticker={ticker} />;
  };
  const buildLeccionesSection = async (): Promise<React.ReactNode> => <DecisionLessonsSection data={await viewData('lecciones')} locale={locale} ticker={ticker} />;

  type TabSection = { id?: string; title?: string; node: React.ReactNode };

  // Las secciones que no encabezan su pestaña degradan a aviso inline con
  // reintento (nunca a vacío fingido ni a una pestaña entera caída); la de
  // entrada conserva el comportamiento de siempre.
  const optionalSection = async (id: string, title: string, build: () => Promise<React.ReactNode>): Promise<TabSection> => {
    try {
      return { id, title, node: await build() };
    } catch (error) {
      console.warn(`[research] ${ticker} · sección ${id} falló: ${error instanceof Error ? error.message : String(error)}`);
      return { id, title, node: <SectionLoadError locale={locale} retryHref={`${tabHref(ticker, tabOfView(activeView))}#${id}`} title={title} /> };
    }
  };

  // Las seis pestañas y sus secciones, en el orden acordado (opción 1).
  let sections: TabSection[];
  if (activeView === 'overview') {
    sections = [
      { node: await buildOverviewContent() },
      await optionalSection('noticias', t('research.fichaSecNoticias'), buildNoticiasSection),
    ];
  } else if (activeView === 'thesis') {
    sections = [{ node: await buildThesisContent() }];
  } else if (activeView === 'financials') {
    sections = [
      { id: 'financieros', title: t('research.fichaSecFinancieros'), node: await buildFinancialsContent() },
      await optionalSection('terminal', t('research.fichaSecTerminal'), buildTerminalSection),
      await optionalSection('dilucion', t('research.fichaSecDilucion'), buildCapitalSection),
    ];
  } else if (activeView === 'valuation') {
    sections = [
      { id: 'valoracion', title: t('research.fichaSecValoracion'), node: await buildValuationContent() },
      await optionalSection('modelo', t('research.fichaSecModelo'), buildModelSection),
      await optionalSection('supuestos', t('research.fichaSecSupuestos'), buildSupuestosSection),
      await optionalSection('oportunidad', t('research.fichaSecOportunidad'), buildMarketOpportunitySection),
      await optionalSection('comparables', t('research.fichaSecComparables'), buildPeersSection),
      await optionalSection('foso', t('research.fichaSecFoso'), buildMoatSection),
    ];
  } else if (activeView === 'changes') {
    sections = [
      { id: 'cambios', title: t('research.fichaSecCambios'), node: await buildChangesContent() },
      await optionalSection('superinversores', t('research.fichaSecSuperinversores'), buildHoldersSection),
      await optionalSection('directiva', t('research.fichaSecDirectiva'), buildDirectivaSection),
      await optionalSection('lecciones', t('research.fichaSecLecciones'), buildLeccionesSection),
      ...(ticker === 'ASTS' ? [await optionalSection('satellites', t('research.fichaSecSatelites'), buildSatellitesSection)] : []),
    ];
  } else {
    sections = [
      { id: 'documentos', title: t('research.fichaSecDocumentos'), node: await buildDocumentsContent() },
      await optionalSection('fuentes', t('research.fichaSecFuentes'), buildSourcesSection),
      { id: 'chat', title: t('research.fichaSecChat'), node: await buildChatSection() },
    ];
  }

  const recentChangeCount = snapshot.recent_changes?.length ?? 0;
  // F143: el distintivo de tenencia sale de la posicion viva del tenant
  // (snapshot.in_portfolio), no de companies.company_type, que es una
  // clase estatica fijada al alta de la ficha y queda desfasada en los
  // dos sentidos (AAPL en cartera decia "candidato de analisis"; SPCX,
  // sin posicion del tenant, "portfolio holding" - ademas en ingles por
  // el fallback de label()). Un company_type portfolio_holding sin
  // posicion viva se muestra como candidato de analisis.
  const holdingBadge = snapshot.in_portfolio
    ? t('research.fichaInPortfolio')
    : companyTypeLabel(company.company_type === 'portfolio_holding' ? 'research_candidate' : company.company_type);

  return (
    <main id="content" tabIndex={-1} className="min-h-screen bg-surface-0 text-gray-100">
      {/* Llegar con ancla (#thesis-change-… desde Inicio, #diario-decisiones):
          el App Router no reintenta el scroll cuando el destino aún no existe
          (Suspense/datos async); este componente sí. */}
      <Suspense fallback={null}><ResearchHashScroll /></Suspense>
      <div className="mx-auto max-w-[1600px]">
        {/* Desde md las migas ya llevan a Research: la flecha solo queda en movil. */}
        <Link className="mb-3 inline-flex min-h-[44px] items-center text-sm text-gray-500 hover:text-gray-200 md:hidden" href="/research"><ArrowLeft className="mr-2 h-4 w-4" />{t('research.fichaBackResearch')}</Link>
        <header className="mb-6 flex flex-col gap-4 border-b border-gray-800 pb-6">
          <div className="flex items-start gap-3 sm:gap-4">
            <CompanyLogo ticker={ticker} name={company.name || ticker} className="size-12 shrink-0 rounded-xl sm:size-14" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 sm:gap-3"><h1 className="text-2xl font-bold sm:text-3xl">{ticker}</h1><span className="inline-flex items-center gap-2">{exchangeDisplayName(company.exchange) ? <Badge variant="outline">{exchangeDisplayName(company.exchange)}</Badge> : null}<Badge variant="outline">{company.currency}</Badge></span></div>
            </div>
            <div className="-mr-2 flex shrink-0 items-center">
              <FollowButton compact symbol={ticker} company={company.name} isFollowed={isFollowed} stateUnknown={watchlistUnknown} />
              {/* Ancla del comando ALERT del buscador (`ASTS ALERT` -> #alerta). */}
              <div id="alerta" className="scroll-mt-6"><QuickAlertButton compact ticker={ticker} currency={company.currency} /></div>
              <CompanyActionsMenu ticker={ticker} changeCount={recentChangeCount} />
            </div>
          </div>
          {/* Nombre y sector a todo el ancho en móvil: dentro de la columna del ticker
              (entre logo y 3 botones) quedaban en ~110px y partían en 3-4 líneas. En
              ≥sm se alinean con la columna del ticker (logo 56px + gap 16px). */}
          <div className="-mt-1 sm:pl-[72px]">
            <p className="text-sm text-gray-400 sm:text-base">{company.name} · {sectorIndustryLine(company.sector, company.industry)}</p>
            <p className="mt-1 inline-flex items-center gap-1 text-xs text-gray-500"><Target className="h-3.5 w-3.5" />{holdingBadge}</p>
          </div>
          <CompanyNavigation ticker={ticker} activeView={activeView} />
          <Suspense fallback={null}><ListingStaleBanner exchange={company.exchange} priceAsOf={headerMarket?.quote?.priceAsOf ?? null} quote={headerQuotePromise} /></Suspense>
          {/* Ancla del comando GP del buscador (`ASTS GP` -> #grafico). */}
          {headerMarket ? <div id="grafico" className="scroll-mt-6"><Suspense fallback={<CompanyHeaderQuoteSkeleton />}><CompanyHeaderQuote compact={activeView !== 'overview'} snapshot={headerMarket} initialQuote={headerQuotePromise} /></Suspense></div> : null}
          <ChangesSinceVisit ticker={ticker} />
          <div className="scroll-mt-6" id="analistas"><MobileCollapse title={t('research.fichaAnalystTargetsTitle')}><Suspense fallback={null}><AnalystTargetsSection symbol={quoteSymbolFor({ exchange: company.exchange ?? undefined, currency: company.currency ?? undefined }, ticker) ?? ticker} currency={company.currency} /></Suspense></MobileCollapse></div>
          <MobileCollapse title={t('research.fichaDcaSignalsTitle')}><Suspense fallback={null}><DcaHitRatesSection ticker={ticker} /></Suspense></MobileCollapse>
        </header>
        {sections.filter((section) => section.id && section.title).length > 1 ? (
          // Sumario local de la pestaña (anclas dentro de la página): nunca
          // otra barra global de menús.
          <nav aria-label={t('research.fichaOnThisPage')} className="mb-6 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {sections.filter((section) => section.id && section.title).map((section) => (
              <a className="inline-flex min-h-[44px] items-center text-gray-500 hover:text-teal-300 sm:min-h-0" href={`#${section.id}`} key={section.id}>
                {section.title}
              </a>
            ))}
          </nav>
        ) : null}
        <div className="space-y-10">
          {sections.map((section, index) => (section.id ? (
            <section aria-label={section.title} className="scroll-mt-24 space-y-5" id={section.id} key={section.id}>
              {section.title ? <h2 className="text-lg font-semibold text-gray-100">{section.title}</h2> : null}
              {section.node}
            </section>
          ) : (
            <div key={`principal-${index}`}>{section.node}</div>
          )))}
        </div>
      </div>
    </main>
  );
}
