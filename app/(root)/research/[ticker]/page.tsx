import { FactCalculatedLabel } from '@/components/research/FactCalculatedLabel';
import BlockedValuation from '@/components/research/BlockedValuation';
import { ThesisSummary } from '@/components/research/ThesisSummary';
import { CompanyNavigation } from '@/components/research/CompanyNavigation';
import BrainAskForm from '@/components/research/BrainAskForm';
import LegacyChatRedirect from '@/components/research/LegacyChatRedirect';
import { ResearchHashScroll } from '@/components/research/ResearchHashScroll';
import { formatResearchMetric } from '@/lib/research/metric-value';
import { financialFormula, financialPeriod, financialVersionLabel } from '@/lib/research/financial-display';
import { changeSummaryText } from '@/lib/research/change-copy';
import ThesisAudioPlayer from '@/components/research/ThesisAudioPlayer';
import MobileCollapse from '@/components/ui/mobile-collapse';
import CompanyActionsMenu from '@/components/research/CompanyActionsMenu';
import { collapseVersionHistory, versionHistoryBadges } from '@/lib/research/version-history';
import { ListingStaleBanner } from '@/components/research/ListingStaleBanner';
import { formatPeerValue, peerMedianText } from '@/lib/research/peer-format';
import { factDisplayAudit, factStalenessNotice } from '@/lib/research/fact-display-audit';
import { groupClaimsByVersion } from '@/lib/research/claim-groups';
import { asView, canonicalViewUrl, tabHref, tabOfView, type View } from '@/lib/research/research-views';
import { FinancialTerminalSection } from '@/components/research/sections/FinancialTerminalSection';
import { ShareCapitalSection } from '@/components/research/sections/ShareCapitalSection';
import { DriverAssumptionsSection } from '@/components/research/sections/DriverAssumptionsSection';
import { ManagementCredibilitySection } from '@/components/research/sections/ManagementCredibilitySection';
import { DecisionLessonsSection } from '@/components/research/sections/DecisionLessonsSection';
import { SectionLoadError } from '@/components/research/sections/SectionLoadError';
import { QuickGlancePanel } from '@/components/research/QuickGlancePanel';
import { getAnalystTargets } from '@/lib/research/analyst-targets';
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
import { auditScoreText, auditStatusLabel } from '@/lib/audit-status-copy';
import { companyTypeLabel, etiquetaTierFuente, etiquetaValor, sectorIndustryLine } from '@/lib/labels';
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
  type ResearchFact,
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
import { formatDate, formatMarketCapUsd, formatMarketDate, formatNumber, formatUserDate, formatUserDateTime, formatMoney, formatPrice, isValidCurrencyCode, NA } from '@/lib/format';
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
function newsDateLabel(event: { date: string; date_source?: string | null }): string {
  // es-ES («16 oct 2026»), no ISO crudo: el resto de la app ya pinta así.
  const day = formatUserDate(event.date);
  // Mismo criterio que NewsEventsFlow y ResearchAssistant: solo 'source' es
  // fecha de publicacion verificada; el resto se etiqueta, nunca se afirma.
  if (event.date_source === 'source') return day;
  if (event.date_source === 'gdelt_first_seen') return `Detectada el ${day}`;
  if (event.date_source === 'ingested_at_fallback') return `Incorporada el ${day}`;
  return `Fecha no verificada (${day})`;
}

function number(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Etiquetas en español para enums persistidos por el backend */
const STATUS_LABELS: Record<string, string> = {
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
const PEERS_BASIS_LABELS: Record<string, string> = {
  traceable_calculated_metric: 'métrica calculada trazable',
  evidence_backed_claim: 'afirmación con evidencia enlazada',
};
const PEERS_METHODOLOGY_ES: Record<string, string> = {
  'Quantitative differences use traceable calculated metrics. Qualitative differences are emitted only when linked evidence exists.':
    'Las diferencias cuantitativas usan métricas calculadas trazables. Las diferencias cualitativas solo se publican cuando existe evidencia enlazada.',
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
    description: `Research de ${name ?? ticker}: tesis versionada, financieros canónicos, modelo a largo plazo, valoración y evidencia con fuentes trazables.`,
  };
}

function label(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NA;
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

function metricValue(value: number | string | null | undefined, unit: string) {
  const parsed = number(value);
  if (parsed === null) return 'desconocido';
  return formatResearchMetric(parsed, unit);
}

/** Fuente de una cifra: enlace real al documento de origen (filing SEC/ESEF o pagina del proveedor) con su fecha, o texto plano cuando no hay documento. Nunca un enlace inventado. */
function FactSource({ fact }: { fact: ResearchFact }) {
  const text = label(fact.source_type);
  if (!fact.source_url) return <>{text}<FactCalculatedLabel fact={fact} /></>;
  const date = fact.source_published_at ? formatUserDate(fact.source_published_at) : null;
  return (
    <>
    <a
      className="text-teal-300 underline-offset-2 transition hover:text-teal-200 hover:underline"
      href={fact.source_url}
      rel="noopener noreferrer"
      target="_blank"
      title={fact.source_title ?? fact.source_url}
    >
      {text}{date ? ` · ${date}` : ''}
    </a>
    <FactCalculatedLabel fact={fact} />
    </>
  );
}

/** La cifra enlaza a su fuente cuando el backend trae URL real del documento. */
function FactValueLink({ fact, children }: { fact: ResearchFact; children: React.ReactNode }) {
  if (!fact.source_url) return <>{children}</>;
  return (
    <a
      className="underline-offset-2 transition hover:text-teal-200 hover:underline"
      href={fact.source_url}
      rel="noopener noreferrer"
      target="_blank"
      title={fact.source_title ?? 'Fuente del dato'}
    >
      {children}
    </a>
  );
}

function FactCard({ fact, ticker, staleness }: { fact: ResearchFact; ticker: string; staleness: string | null }) {
  const audit = factDisplayAudit(ticker, fact);
  return (
    <div className="rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-gray-200">{metricLabel(fact.metric)}</span>
        <span className={`text-sm font-semibold ${audit ? 'text-gray-400' : 'text-teal-300'}`}>{audit ? 'N/D' : <FactValueLink fact={fact}>{metricValue(fact.value, fact.unit)}</FactValueLink>}</span>
      </div>
      {audit ? <p className="mt-2 text-xs text-amber-300">{audit}</p> : null}
      {!audit && staleness ? <p className="mt-2 text-xs text-amber-300">{staleness}</p> : null}
      <div className="mt-1.5 flex flex-wrap gap-2 text-xs text-gray-500">
        <span>{financialPeriod(fact.period)}</span>
        <span>·</span>
        <span><FactSource fact={fact} /></span>
      </div>
    </div>
  );
}

/** Hechos visibles en móvil antes del «ver más» */
const FACTS_MOBILE_PAGE = 10;

/** Un borrador o una tesis en revisión no enseña veredicto ni cifras (regla vigente, igual que el memo y el PDF). */
function thesisIsPublic(status: string | null | undefined): boolean {
  return status === 'published' || status === 'approved';
}

function FactTable({ facts, refreshLabel, ticker }: { facts: ResearchFact[]; refreshLabel: string; ticker: string }) {
  if (!facts.length) {
    return (
      <EmptyState
        description={`Pulsa «${refreshLabel}» arriba para traerlos del proveedor indicado. Si sigue vacío, no hay datos persistidos: comprueba el resultado del refresh y la fuente.`}
        title="Todavía no hay hechos financieros persistidos."
      />
    );
  }
  // El último hecho de cada métrica (la lista viene ordenada por año fiscal
  // descendente) es el que un lector toma por «estado actual».
  const latestFiscalYear = facts.reduce((acc, fact) => Math.max(acc, fact.fiscal_year ?? 0), 0) || null;
  const latestIdByMetric = new Map<string, number>();
  for (const fact of facts) {
    if (!latestIdByMetric.has(fact.metric)) latestIdByMetric.set(fact.metric, fact.id);
  }
  const stalenessOf = (fact: ResearchFact) =>
    factStalenessNotice(fact, { isLatestForMetric: latestIdByMetric.get(fact.metric) === fact.id, latestFiscalYear });
  const hasUnofficial = facts.some((fact) => String(fact.source_type ?? '').toUpperCase() === 'YAHOO_FUNDAMENTALS');
  return (
    <>
      {hasUnofficial ? (
        <p className="mb-3 text-xs text-amber-300" role="note">
          Incluye cifras de una fuente no oficial (Yahoo Finance), sin auditar ni contrastar con el emisor; la fuente de cada fila aparece a la derecha.
        </p>
      ) : null}
      {/* Móvil: cards paginadas (Anterior/Siguiente), sin «ver más» ni corte silencioso */}
      <div className="space-y-3 md:hidden">
        <PagedList
          items={facts.map((fact) => ({ key: `fact-${fact.id}`, node: <FactCard fact={fact} staleness={stalenessOf(fact)} ticker={ticker} /> }))}
          label="Hechos financieros"
          pageSize={FACTS_MOBILE_PAGE}
        />
      </div>
      {/* Escritorio: tabla completa */}
      <div aria-label="Hechos financieros" className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Hechos financieros de la empresa (oficiales y, si se indica, no oficiales): métrica, periodo, valor y fuente</caption>
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="border-b border-gray-800 py-2" scope="col">Métrica</th>
            <th className="border-b border-gray-800 py-2" scope="col">Periodo</th>
            <th className="border-b border-gray-800 py-2 text-right" scope="col">Valor</th>
            <th className="border-b border-gray-800 py-2 text-right" scope="col">Fuente</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((fact) => (
            <tr key={fact.id} className="text-gray-300">
              <th className="border-b border-gray-900 py-2 text-left text-sm font-medium" scope="row">{metricLabel(fact.metric)}</th>
              <td className="border-b border-gray-900 py-2">{financialPeriod(fact.period)}</td>
              <td className="border-b border-gray-900 py-2 text-right">{factDisplayAudit(ticker, fact) ? <span className="text-gray-400">N/D<span className="mt-1 block text-xs text-amber-300">{factDisplayAudit(ticker, fact)}</span></span> : <><FactValueLink fact={fact}>{metricValue(fact.value, fact.unit)}</FactValueLink>{stalenessOf(fact) ? <span className="mt-1 block text-xs text-amber-300">{stalenessOf(fact)}</span> : null}</>}</td>
              <td className="border-b border-gray-900 py-2 text-right text-xs text-gray-500"><FactSource fact={fact} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </>
  );
}

function MetricsGrid({ metrics }: { metrics: ResearchCalculatedMetric[] }) {
  if (!metrics.length) {
    return (
      <EmptyState
        description="Las métricas se derivan de los hechos financieros: pulsa «Recalcular» arriba. Si todavía no hay hechos, refresca primero los financieros con el botón de actualización correspondiente."
        title="Las métricas calculadas aún no se han refrescado."
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
            <span className="min-w-0 break-all font-medium text-gray-200">{metricLabel(metric.metric)}</span>
            <Badge className="shrink-0" variant="outline">{label(metric.status)}</Badge>
          </div>
          <div className="mt-2 text-xl text-teal-300">{metricValue(metric.value, metric.unit)}</div>
          <div className="mt-2 text-xs text-gray-500">{financialPeriod(metric.period)} · {financialVersionLabel(metric.definition_version)}</div>
          <div className="mt-2 text-xs leading-5 text-gray-400">{financialFormula(metric.formula)}</div>
        </div>
      ))}
    </div>
  );
}

function ValuationView({ valuation, currency, ticker }: { valuation: ResearchValuation | null; currency: string; ticker: string }) {
  if (!valuation) {
    return (
      <EmptyState
        action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>Genera primero el modelo a largo plazo</EmptyLink>}
        title="No hay ninguna valoración persistida."
      />
    );
  }
  if (valuation.status === 'insufficient_data') {
    return <BlockedValuation valuation={valuation} ticker={ticker} />;
  }
  const engine = typeof valuation.trace?.engine === 'string' ? valuation.trace.engine : null;
  const method = typeof valuation.trace?.method === 'string' ? valuation.trace.method : null;
  const inputSource = typeof valuation.trace?.input_source === 'string' ? valuation.trace.input_source : null;
  const periods = Object.entries(valuation.trace?.periods ?? {})
    .filter(([, value]) => value)
    .map(([metric, period]) => `${termLabel(metric)}: ${period}`)
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
    ? `Precio del modelo al ${formatMarketDate(priceAsOf, { day: 'numeric', month: 'short' })}`
    : 'Precio del modelo (sin fecha)';
  if (notPublishable) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label={modelPriceLabel} value={formatMoney(valuation.current_price, currency)} />
        </div>
        <div className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-4 text-sm text-amber-200">
          <p className="font-semibold">Orientación del motor, no precio objetivo.</p>
          <p className="mt-1">
            Esta valoración no es publicable (estado {label(valuation.status ?? 'unknown')}): los números de
            abajo son una orientación del motor, no una valoración final ni un precio objetivo.
          </p>
          {blockers.length ? <p className="mt-2 text-xs">Motivos registrados: {blockers.map(termLabel).join(', ')}.</p> : null}
          {missingInputs.length ? <p className="mt-2 text-xs">Entradas faltantes: {missingInputs.map(termLabel).join(', ')}.</p> : null}
          {engineNotice ? <p className="mt-2 text-xs text-amber-200/70">Nota del motor: {engineNotice}</p> : null}
        </div>
        <div className="grid grid-cols-1 gap-4 opacity-60 sm:grid-cols-3">
          <Stat label={`Bear (orientación)${basisLabel}`} value={formatMoney(scenarios.values.bear as number | null, currency)} />
          <Stat label={`Base (orientación)${basisLabel}`} value={formatMoney(scenarios.values.base as number | null, currency)} />
          <Stat label={`Bull (orientación)${basisLabel}`} value={formatMoney(scenarios.values.bull as number | null, currency)} />
        </div>
        <p className="text-xs leading-5 text-gray-500">
          Valoración persistida ({termLabel(valuation.model_type)}{engine ? ` · motor ${engine}` : ''}{method ? ` · ${method}` : ''} · estado {label(valuation.status ?? 'unknown')}).
          El «valor por acción» del Modelo a largo plazo es otro cálculo (otra versión/fecha/motor).
          Fuente de datos: {inputSource ?? NA}{periods ? ` · periodos ${periods}` : ` · periodos ${NA}`}.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={modelPriceLabel} value={formatMoney(valuation.current_price, currency)} />
        <Stat label={`Bear${basisLabel}`} value={formatMoney(scenarios.values.bear as number | null, currency)} />
        <Stat label={`Base${basisLabel}`} value={formatMoney(scenarios.values.base as number | null, currency)} />
        <Stat label={`Bull${basisLabel}`} value={formatMoney(scenarios.values.bull as number | null, currency)} />
      </div>
      <p className="text-xs leading-5 text-gray-500">
        Valoración persistida ({termLabel(valuation.model_type)}{engine ? ` · motor ${engine}` : ''}{method ? ` · ${method}` : ''} · estado {label(valuation.status ?? 'unknown')}).
        No es comparable 1:1 con el «valor por acción» del Modelo a largo plazo: ese es un cálculo interno
        del escenario (otra versión/fecha/motor). Antes de fiarte, comprueba versión y fecha en ambas vistas.
        Fuente de datos: {inputSource ?? NA}{periods ? ` · periodos ${periods}` : ` · periodos ${NA}`}.
      </p>
    </div>
  );
}

function MarketOpportunityView({ model, ticker }: { model: ResearchLongTermModel | null; ticker: string }) {
  if (!model || model.status === 'not_generated') {
    return (
      <EmptyState
        action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>Generar el modelo a largo plazo</EmptyLink>}
        title="Genera el modelo a largo plazo antes de valorar la oportunidad de mercado."
      />
    );
  }
  const opportunity = model.market_opportunity;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat label="TAM (mercado total)" value={metricValue(opportunity.top_down.tam.value, opportunity.top_down.tam.unit)} />
        <Stat label="SAM (mercado atendible)" value={metricValue(opportunity.top_down.sam.value, opportunity.top_down.sam.unit)} />
        <Stat label="SOM (mercado obtenible)" value={metricValue(opportunity.top_down.som.value, opportunity.top_down.som.unit)} />
      </div>
      <Panel title="Veredicto con restricciones">
        <div className="flex flex-wrap gap-2">
          <Badge>{label(opportunity.verdict.label)}</Badge>
          <Badge variant="outline">confianza: {label(opportunity.verdict.confidence)}</Badge>
          <Badge variant="outline">restricción ligante: {opportunity.constraints.binding_constraint ? termLabel(opportunity.constraints.binding_constraint) : 'desconocida'}</Badge>
        </div>
        <p className="mt-3 text-sm text-gray-300">{opportunity.verdict.conclusion}</p>
      </Panel>
      <Panel title="Fórmulas bottom-up">
        <div className="space-y-3">
          {opportunity.bottom_up.formulas.map((formula) => (
            <div className="rounded-lg border border-gray-800 p-3" key={formula.label}>
              <div className="flex justify-between gap-4 text-sm">
                <span className="text-gray-200">{formula.label}</span>
                <span className="text-teal-300">{formula.value === null ? label(formula.status) : metricValue(formula.value, formula.unit ?? '')}</span>
              </div>
              {formula.missing_inputs?.length ? <p className="mt-2 text-xs text-amber-300">Faltan entradas: {formula.missing_inputs.map(termLabel).join(', ')}</p> : null}
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
  const ticker = rawTicker.trim().toUpperCase();
  if (rawTicker !== ticker) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (typeof value === 'string') search.set(key, value);
    }
    redirect(`/research/${encodeURIComponent(ticker)}${search.size ? `?${search.toString()}` : ''}`);
  }
  // URLs antiguas de módulo o de grupo histórico (?view=moat, ?view=numeros):
  // una redirección a la URL canónica de su pestaña (una URL por contenido),
  // conservando el resto de parámetros (?chat=, ?pagina=, controles del terminal).
  const canonicalView = canonicalViewUrl(ticker, query.view);
  if (canonicalView) {
    const hashAt = canonicalView.indexOf('#');
    const hash = hashAt >= 0 ? canonicalView.slice(hashAt) : '';
    const withoutHash = hashAt >= 0 ? canonicalView.slice(0, hashAt) : canonicalView;
    const [pathnamePart, viewPart] = withoutHash.split('?view=');
    const search = new URLSearchParams();
    if (viewPart) search.set('view', viewPart);
    for (const [key, value] of Object.entries(query)) {
      if (key !== 'view' && typeof value === 'string') search.set(key, value);
    }
    redirect(`${pathnamePart}${search.size ? `?${search.toString()}` : ''}${hash}`);
  }
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
      return <BackendOffline feature={`Research de ${ticker}`} retryHref={`/research/${ticker}`} />;
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
              description={`La identidad de ${ticker} está verificada por doble coincidencia SEC + proveedor de mercado: «${verification.sec.name}» (${verification.provider.exchange}${verification.provider.currency ? `, ${verification.provider.currency}` : ', divisa N/D'}). La ficha aún no existe en GerarAI: se crea solo si la abres, y nacerá sin research generado.`}
              icon={ShieldAlert}
              title="Identidad verificada por dos fuentes"
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
      ? ' Se comprobó la doble coincidencia SEC + proveedor de mercado y no se cumplió, así que la identidad sigue sin verificar.'
      : '';
    const state =
      identity.kind === 'unverified'
        ? {
            title: 'Identidad del ticker no verificada',
            description: `${ticker} no tiene identidad de listado verificada en GerarAI: el proveedor de mercado conoce este símbolo como «${identity.providerName}», que puede no ser el emisor que buscas. Sin identidad verificada no se pueden mostrar datos ni generar research de este símbolo.${doubleCheckNote}`,
          }
        : identity.kind === 'not-in-sources'
          ? {
              title: 'No encontramos este ticker en nuestras fuentes',
              description: `Ninguna de nuestras fuentes reconoce ${ticker}: puede que el símbolo sea incorrecto o que aún no tenga cobertura verificada. Sin identidad verificada no se pueden mostrar datos ni generar research de este símbolo.`,
            }
          : {
              title: 'No pudimos comprobar este ticker',
              description: `${ticker} no está en la cobertura verificada de GerarAI y el proveedor de mercado no está disponible para comprobarlo. Sin identidad verificada no se pueden mostrar datos ni generar research de este símbolo; inténtalo de nuevo más tarde.`,
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
                  Buscar otra empresa
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
    return <BackendOffline feature={`Research de ${ticker}`} retryHref={viewRetryHref(ticker, activeView)} />;
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
    // marketPromise ya se lanzó en paralelo al snapshot más arriba.
    let market: Awaited<ReturnType<typeof getCompanyMarketSnapshot>>;
    try {
      // headerMarket ya guarda esta misma promesa resuelta (se esperó en la
      // cabecera); aquí solo se distingue la caída del motor del resto.
      market = await marketPromise;
    } catch (error) {
      if (isBackendUnavailableError(error)) {
        return <BackendOffline feature={`Datos de mercado de ${ticker}`} retryHref={`/research/${ticker}`} />;
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
      getCompanyPer(ticker, { exchange: company.exchange ?? undefined, currency: company.currency ?? undefined }).catch(() => ({ value: null, note: 'No se pudo consultar el PER' })),
      getOwnershipSignals(ticker).catch(() => null),
      snapshot.in_portfolio
        ? getCompanyHolding(ticker).catch(() => ({ status: 'error' as const, message: 'No se pudo cargar tu posición en esta empresa.' }))
        : Promise.resolve(null),
    ]);
    // Panel de vistazo rápido: datos reales ya existentes, cada fila a su
    // sección. En móvil va arriba (bajo el precio de la cabecera); en PC
    // es la columna lateral derecha (estilo Investing, opción 1).
    const [glanceModel, glanceCapital, glanceCredibility, glanceAnalysts] = await Promise.all([
      glanceModelPromise ?? Promise.resolve(null),
      glanceCapitalPromise ?? Promise.resolve(null),
      glanceCredibilityPromise ?? Promise.resolve(null),
      getAnalystTargets(quoteSymbolFor({ exchange: company.exchange ?? undefined, currency: company.currency ?? undefined }, ticker) ?? ticker).catch(() => null),
    ]);
    return (
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(280px,320px)]">
        <div className="min-w-0 xl:order-2">
          <QuickGlancePanel
            analysts={glanceAnalysts}
            credibility={glanceCredibility}
            currency={company.currency}
            livePrice={headerMarket?.quote?.price ?? null}
            moatScore={moatScore}
            model={glanceModel}
            shareCapital={glanceCapital}
            ticker={ticker}
          />
        </div>
        <div className="min-w-0 space-y-6 xl:order-1">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel density="compact" title="Última tesis">
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
                      <FileText className="mr-2 h-4 w-4" />Leer tesis completa
                    </Link>
                  </Button>
                  <ThesisGenerateButton ticker={ticker} label="Regenerar tesis" />
                </div>
              </>
            ) : (
              <ThesisGenerateButton ticker={ticker} label="Genera la primera tesis" emptyCopy="Sin tesis todavía." />
            )}
          <dl className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
            <div className="flex items-baseline gap-1.5"><dt className="text-gray-500">PER (TTM)</dt><dd className="font-semibold text-gray-100">{per.value !== null ? `${formatNumber(per.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}x` : NA}</dd></div>
            {snapshot.model_summary ? <div className="flex items-baseline gap-1.5"><dt className="text-gray-500">Modelo</dt><dd className="font-semibold text-gray-100"><Link className="inline-flex min-h-11 min-w-11 items-center underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>{snapshot.model_summary.publishable ? 'publicable' : 'bloqueado'}</Link></dd></div> : null}
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
              Ver todas
            </Link>
          }
          description="Las 5 noticias de mayor materialidad entre las 25 más recientes de esta empresa, con fuente y fecha."
          title="Últimas noticias"
        >
          {overviewNewsError ? (
            <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
              No se pudieron cargar las noticias. Reintenta en unos segundos.
            </p>
          ) : overviewNews.length === 0 ? (
            <EmptyState title="Sin noticias recientes de esta empresa." />
          ) : (
            <ul className="space-y-3">
              {overviewNews.map((event) => (
                <li className="text-sm" key={event.id}>
                  <NewsHeadline event={event} />
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                    <ImpactBadge direction={event.impact_direction} />
                    <span>{event.source} · {newsDateLabel(event)}</span>
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
              Ver todos los cambios
            </Link>
          }
          density="compact"
          title="Últimos cambios"
        >
          {snapshot.recent_changes?.length ? (
            <ul className="space-y-2">
              {snapshot.recent_changes.slice(0, 3).map((change) => (
                <li className="min-w-0 rounded-lg border border-gray-800/70 bg-black/20 p-3 text-sm text-gray-300" key={change.id}>
                  <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                    <Badge variant="outline">{label(change.impact_direction)}</Badge>
                    <span className="text-xs text-gray-500">
                      Materialidad {change.materiality_score} · {formatDate(change.created_at)}
                    </span>
                  </div>
                  <p className="break-words leading-6 [overflow-wrap:anywhere]">{changeSummaryText(change.summary)}</p>
                  {/* Procedencia: fuente del evento y URLs absorbidas al agrupar
                      la misma noticia en dos idiomas (identidad atribuida). */}
                  {change.fuente_url && /^https:\/\//.test(change.fuente_url) ? (
                    <p className="mt-1 text-xs text-gray-500">
                      <a href={change.fuente_url} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">
                        {change.fuente_nombre || 'Fuente'}
                      </a>
                      {(change.tambien_en ?? []).map((entry, entryIndex) => {
                        const url = typeof entry?.url === 'string' ? entry.url : null;
                        const nombre = typeof entry?.fuente === 'string' ? entry.fuente : 'otra fuente';
                        return url && /^https:\/\//.test(url) ? (
                          <span key={`${url}-${entryIndex}`}>
                            {' · también en '}
                            <a href={url} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">{nombre}</a>
                          </span>
                        ) : null;
                      })}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-500">Sin cambios registrados desde la última revisión.</p>
          )}
        </Panel>
        {snapshot.research_health.missing?.length ? (
          <MobileCollapse title={`Capas de research que faltan (${snapshot.research_health.missing.length})`}>
          <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200">
            <p>Capas de research que faltan:</p>
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
              Ver la evaluación del foso
            </Link>
          ) : undefined}
          title="Calidad financiera según la empresa"
        >
          {moatScore ? (
            <MoatPanel company={company} metric={moatScore} />
          ) : (
            <EmptyState title="Sin evaluación de calidad generada todavía: aparece con el refresco de las métricas financieras de la empresa." />
          )}
        </Panel>
        {/*
            Los cuatro saltos que se piden antes que nada al abrir una ficha.
            Están aquí, en el resumen, y no repartidos por las 16 píldoras
            planas que había antes.
        */}
        <Panel className="hidden md:block" collapsible="mobile"
          description="Dónde está el resto del análisis de esta empresa."
          density="compact"
          title="Por dónde seguir"
        >
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
            {[
              ['Modelo a largo plazo', 'valoracion#modelo'],
              ['Oportunidad de mercado', 'valoracion#oportunidad'],
              ['Comparables', 'valoracion#comparables'],
              ['Documentos y fuentes', 'fuentes#documentos'],
            ].map(([nextLabel, nextView]) => (
              <NextStepLink href={`/research/${encodeURIComponent(ticker)}?view=${nextView}`} key={nextView}>
                {nextLabel}
              </NextStepLink>
            ))}
          </div>
        </Panel>
        <OwnershipSignalsPanel signals={ownershipSignals} ticker={ticker} />
        {ticker === 'ASTS' ? <Panel collapsible="mobile" title="Satélites AST"><Link className="mt-2 inline-block text-sm text-teal-300" href={`/research/${encodeURIComponent(ticker)}?view=seguimiento#satellites`}>Ver señal orbital exploratoria</Link></Panel> : null}
        <p role="status" className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200">
          {researchValuability(snapshot)}
        </p>
        {/* Price chart lives once in the company header, across all views. */}
        </div>
      </div>
    );
  };

  const buildNoticiasSection = async (): Promise<React.ReactNode> => {
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
      <Panel title="Noticias de la empresa">
        <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
          No se pudieron cargar las noticias. Reintenta en unos segundos.
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
              ...(snapshot?.model_summary && !snapshot.model_summary.publishable ? ['La valoración es parcial o está bloqueada: no es un valor justo final.'] : []),
              ...((data.thesis?.missing_inputs?.length ?? 0) > 0 ? [`Faltan ${data.thesis?.missing_inputs?.length} inputs del modelo (ver «Datos pendientes»).`] : []),
              ...(typeof data.thesis?.red_team_score === 'number' && data.thesis.red_team_score < 40 ? [`El red team puntúa ${data.thesis.red_team_score}/100.`] : []),
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
          <Badge variant="outline">{data.history.length} versiones</Badge>
          <Badge variant="outline">{data.claims.length} afirmaciones</Badge>
        </div>
        <Panel title="Historial de versiones y aprobaciones" collapsible="mobile">
          {data.historyDetail.history.length === 0 ? (
            <EmptyState title="Aún no hay historial de versiones." />
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
                          <Badge variant="outline">{group.length} versiones seguidas con el mismo resumen (v{entry.version}–v{group[group.length - 1].version})</Badge>
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
                        <p className="mt-2 text-xs text-gray-500">Primera versión registrada o sin diff persistido.</p>
                      )}
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                        <span>red-team {entry.red_team_score}/100</span>
                        <span>confianza datos {entry.data_confidence_score}/100</span>
                      </div>
                    </div>
                  ),
                };
              })}
              label="Historial de versiones y aprobaciones"
              pageSize={10}
            />
          )}
          <p className="mt-3 text-xs text-gray-500">
            El historial muestra estado, fecha y resumen del cambio tal como están persistidos; el sistema no registra quién aprobó cada versión.
          </p>
        </Panel>
        <ThesisAudioPlayer
          ticker={ticker}
          version={data.historyDetail.history.filter((entry) => entry.status === 'published').reduce<number | null>((a, entry) => (a === null ? entry.version : Math.max(a, entry.version)), null)}
        />
        <div id="tesis-actual" style={{ scrollMarginTop: '5rem' }}>
        <Panel title="Tesis actual">
          {data.thesis ? (
            <ThesisMemo
              thesis={data.thesis}
              ticker={ticker}
              currency={company.currency}
              model={snapshot?.model_summary}
              extraSections={data.sections.filter((section) => section.section_key !== 'thesis_debate')}
              debateBody={
                data.sections.find((section) => section.section_key === 'thesis_debate')?.body ?? null
              }
            />
          ) : (
            <EmptyState
              action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=fuentes`}>Importa fuentes antes de generar</EmptyLink>}
              title="Aún no existe ninguna tesis."
            />
          )}
        </Panel>
        </div>
        <ThesisScenariosPanel adrRatio={data.thesis?.valuation_basis?.adr_ratio} currency={company.currency} data={data.scenarios} />
        <Panel title="Afirmaciones y evidencia">
          <ResearchClaimForm action={createResearchClaim.bind(null, ticker)} />
          <div className="space-y-3">
            {data.claims.length ? groupClaimsByVersion(data.claims, data.history).map((group) => (
              <details key={group.key} open={group.claims.some((claim) => claim.thesis_version_id === data.thesis?.id)} className="rounded-lg border border-gray-800 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-gray-300">{group.label} · {group.claims.length} afirmaciones</summary>
                <PagedList
                  className="mt-3"
                  items={group.claims.map((claim) => ({
                    key: `claim-${claim.id}`,
                    node: (
                      <div className="rounded-lg border border-gray-800 p-4">
                        <div className="flex flex-wrap gap-2"><Badge variant="outline">{label(claim.status)}</Badge><Badge variant="outline">materialidad {claim.materiality_score}</Badge><Badge variant="outline">{claim.evidence.length} pruebas</Badge></div>
                        <p className="mt-3 text-sm text-gray-300">{claim.statement}</p>
                      </div>
                    ),
                  }))}
                  label={`Afirmaciones de ${group.label}`}
                  pageSize={10}
                />
              </details>
            )) : (
              <EmptyState
                action={<EmptyLink href="#statement">Escribe la primera afirmación</EmptyLink>}
                title="Sin afirmaciones registradas."
              />
            )}
          </div>
        </Panel>
      </div>
    );
  };

  const buildChangesContent = async (): Promise<React.ReactNode> => {
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
          <Panel title="Qué ha cambiado">
            <EmptyState
              action={<EmptyLink href="/research/news">Analiza la última noticia</EmptyLink>}
              title="Sin cambios materiales registrados."
            />
          </Panel>
        )}
        <GuideContextPanel ticker={ticker} context={guideContext} hideReviews />
        <DecisionAndRealityPanel ticker={ticker} decisions={data.decisions} reviews={data.expectations} trades={data.trades} />
        <CompanyPaperTrades state={paperTrades} ticker={ticker} />
      </div>
    );
  };

  const buildHoldersSection = async (): Promise<React.ReactNode> => {
    const holders = await viewData('holders');
    // Propietarios = 13F (gestores) + insiders (Form 4, SEC EDGAR, gratis).
    // Los Form 4 persistidos se leen del backend; sin red ni proveedor de
    // pago. Best-effort: cualquier fallo degrada a panel vacio honesto.
    const insiderFilings = await getInsiderFilings(ticker, 8).catch(() => null);
    return (
      <div className="space-y-6">
        {holders === null ? (
          <EmptyState title="No se pudieron cargar los superinversores de esta empresa." />
        ) : holders.status === 'sin_identificador' ? (
          <EmptyState title={holders.identity_source ?? 'Sin identidad CUSIP verificada para cruzar los 13F.'} />
        ) : holders.status === 'sin_datos' ? (
          <EmptyState title="Sin informes 13F sincronizados." />
        ) : (
          <Panel title="Superinversores que la declaran">
            {holders.holders.length ? (
              <ul className="space-y-3">
                {holders.holders.map((holder) => (
                  <li className="rounded-lg border border-gray-800 p-3 text-sm" key={holder.slug}>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <Link className="font-medium text-teal-300 hover:text-teal-200" href={`/inversores/${holder.slug}`}>{holder.name}</Link>
                      <span className="text-gray-200">{holder.value_usd !== null ? formatMarketCapUsd(holder.value_usd) : NA}</span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      Cartera a {holder.report_date ? formatDate(holder.report_date) : 'fecha desconocida'}
                      {holder.coverage === 'partial' ? ' · Datos parciales' : ''}
                      {holder.filing_url ? (
                        <>
                          {' · '}
                          <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={holder.filing_url} rel="noopener noreferrer" target="_blank">13F original</a>
                        </>
                      ) : null}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="Ningún gestor revisado la declara en su último 13F." />
            )}
            <p className="mt-4 text-xs text-gray-500">
              {holders.managers_with_data} gestores con datos · {holders.managers_without_data} sin datos
              {holders.managers_partial ? ` · ${holders.managers_partial} parciales` : ''} · {holders.limitations.join(' ')}
            </p>
          </Panel>
        )}
        <Panel title="Insiders (Form 4 · SEC EDGAR)">
          {insiderFilings === null || insiderFilings.status !== 'ok' || insiderFilings.filings.length === 0 ? (
            insiderFilings?.foreign_issuer ? (
              <EmptyState
                description="Los emisores privados extranjeros están exentos de la Sección 16 de la SEC: no presentan Form 4. Sus insiders declaran en el registro de su país (p. ej. SEDI en Canadá, NSM/FCA en Reino Unido), no en EDGAR."
                title="Sin Form 4: emisor extranjero"
              />
            ) : (
              <EmptyState title="Sin operaciones insider persistidas para este ticker." />
            )
          ) : (
            <ul className="space-y-3">
              {insiderFilings.filings.map((filing) => (
                <li className="rounded-lg border border-gray-800 p-3 text-sm" key={filing.accession_number}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-gray-300">
                      {filing.form}{filing.is_amendment ? ' (enmienda)' : ''} · {filing.filing_date ? formatDate(filing.filing_date) : 'fecha desconocida'}
                    </span>
                    {safeHttpUrl(filing.source_url) ? (
                      <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={safeHttpUrl(filing.source_url) ?? undefined} rel="noopener noreferrer" target="_blank">Form 4 original</a>
                    ) : null}
                  </div>
                  <ul className="mt-2 space-y-1 text-xs text-gray-400">
                    {filing.transactions.slice(0, 6).map((tx, index) => (
                      <li key={`${filing.accession_number}-${index}`}>
                        {insiderName(tx.insider)} · {insiderRole(tx.role, tx.officer_title)} · {tx.code === 'P' ? 'Compra' : tx.code === 'S' ? 'Venta' : tx.code ?? '—'}
                        {typeof tx.shares === 'number' ? ` · ${formatNumber(tx.shares)} acciones` : ''}
                        {typeof tx.value === 'number' && Number.isFinite(tx.value) ? ` · ${tx.currency && isValidCurrencyCode(tx.currency) ? formatPrice(tx.value, tx.currency, { minimumFractionDigits: 0, maximumFractionDigits: 0 }) : formatNumber(tx.value, { maximumFractionDigits: 0 })}` : ''}
                        {tx.currency == null && typeof tx.value === 'number' ? ' · divisa no informada' : ''}
                        {tx.tx_date ? ` · ${formatDate(tx.tx_date)}` : ''}
                      </li>
                    ))}
                  </ul>
                  {filing.transactions.length > 6 ? (
                    <p className="mt-1 text-xs text-gray-500">Se muestran 6 de {formatNumber(filing.transactions.length, { maximumFractionDigits: 0 })} operaciones de este formulario.</p>
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
    const data = await viewData('financials');
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap gap-3">
          {/* FMP plan free solo cubre mercado US (402 en el resto): el boton
              solo se ofrece cuando el emisor entra en esa cobertura (B30).
              La decision usa el perfil (mercado declarado), no solo el
              sufijo del ticker: los europeos canonicos no lo llevan (AENA). */}
          {fmpCovers(ticker, company.exchange) ? (
            <MutationForm action={refreshCompanyFinancials.bind(null, ticker)} successMessage="Financieros actualizados (FMP)"><Button type="submit" variant="outline">Refrescar financieros (FMP)</Button></MutationForm>
          ) : null}
          {isEsefIssuerProfile(ticker, company.exchange) ? (
            <MutationForm action={refreshCompanyFinancialsESEF.bind(null, ticker)} successMessage="Financieros ESEF refrescados"><Button type="submit" variant="outline">Refrescar ESEF</Button></MutationForm>
          ) : (
            <MutationForm action={refreshCompanyFinancialsSEC.bind(null, ticker)} successMessage="Financieros SEC refrescados"><Button type="submit" variant="outline">Refrescar SEC</Button></MutationForm>
          )}
          <MutationForm action={refreshCompanyResearchModel.bind(null, ticker)} successMessage="Métricas y modelo de research refrescados"><Button type="submit"><RefreshCcw className="mr-2 h-4 w-4" />Recalcular</Button></MutationForm>
        </div>
        <Panel title="Fundamentales actuales · TTM (últimos 4 trimestres)"><TtmPanel ttm={data.ttm} /></Panel>
        <Panel title="Métricas calculadas trazables"><MetricsGrid metrics={data.calculatedMetrics} /></Panel>
        <Panel title="Hechos financieros canónicos"><FactTable ticker={ticker} facts={data.facts} refreshLabel={
            fmpCovers(ticker, company.exchange)
              ? 'Refrescar financieros (FMP)'
              : isEsefIssuerProfile(ticker, company.exchange)
                ? 'Refrescar ESEF'
                : 'Refrescar SEC'
          } /></Panel>
      </div>
    );
  };

  const buildModelSection = async (): Promise<React.ReactNode> => {
    const model = await viewData('model');
    return (
      <div className="space-y-5">
        <MutationForm action={refreshCompanyResearchModel.bind(null, ticker)} successMessage="Modelo a largo plazo generado"><Button type="submit"><RefreshCcw className="mr-2 h-4 w-4" />Generar modelo</Button></MutationForm>
        <LongTermModelPanel model={model?.status === 'not_generated' ? null : model} ticker={ticker} />
      </div>
    );
  };

  const buildMarketOpportunitySection = async (): Promise<React.ReactNode> => {
    return <MarketOpportunityView model={await viewData('model')} ticker={ticker} />;
  };

  const buildMoatSection = async (): Promise<React.ReactNode> => {
    const moat = await viewData('moat');
    return (
      <div className="space-y-5">
        <MutationForm action={refreshCompanyResearchModel.bind(null, ticker)} successMessage="Evaluación del foso refrescada"><Button type="submit" variant="outline"><ShieldCheck className="mr-2 h-4 w-4" />Reevaluar evidencia</Button></MutationForm>
        <MoatClassificationPanel moat={moat} />
        <MoatChecklistPanel moat={moat} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {moat?.moats.length ? moat.moats.map((item) => {
            const definition = moatDefinition(item.type);
            return (
              <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={item.type}>
                <div className="flex justify-between gap-3"><MoatTerm type={item.type} /><Badge>{item.strength}/100</Badge></div>
                <p className="mt-3 text-sm text-gray-400">{label(item.status)} · {label(item.trend)} · persistencia {label(item.persistence)}</p>
                {definition ? <p className="mt-2 text-xs leading-5 text-gray-500">{definition}</p> : null}
                <p className="mt-2 text-xs text-gray-500">{item.supporting_claim_ids.length} afirmaciones a favor · {item.contradicting_claim_ids.length} en contra</p>
              </div>
            );
          }) : (
            <EmptyState
              action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=valoracion#modelo`}>Genera el modelo y reevalúa el foso</EmptyLink>}
              title="Sin evaluación de foso persistida."
            />
          )}
        </div>
      </div>
    );
  };

  const buildSatellitesSection = async (): Promise<React.ReactNode> => {
    // El panel ya degrada solo cuando no hay datos; aquí la lectura llega del
    // lote en paralelo (null si degradó, igual que antes).
    const satellites = ticker === 'ASTS' ? await viewData('satellites') : null;
    return ticker === 'ASTS' ? <AstOrbitPanel data={satellites?.orbits ?? null} analysis={satellites?.analysis ?? null} /> : <EmptyState title="Esta vista orbital solo está disponible para ASTS." />;
  };

  const buildPeersSection = async (): Promise<React.ReactNode> => {
    const peers = await viewData('peers');
    return (
      <div className="space-y-6">
        <Panel title="Conjunto de comparables"><p className="text-sm text-gray-300">{peers.comparison?.basis ? (PEERS_BASIS_LABELS[peers.comparison.basis] ?? peers.comparison.basis) : 'Sin conjunto de comparables'} · {peers.comparison?.peer_count ?? 0} comparables con datos{(peers.comparison?.peers_without_data ?? []).length > 0 ? ` · sin datos: ${(peers.comparison?.peers_without_data ?? []).join(', ')}` : ''}</p><div className="mt-4 flex flex-wrap gap-2">{peers.comparison?.companies.map((peer) => <Badge variant={peer.is_target ? 'default' : 'outline'} key={peer.ticker}>{peer.ticker}</Badge>)}</div></Panel>
        <Panel title="Métricas comparables"><div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{Object.entries(peers.comparison?.benchmarks ?? {}).map(([metric, value]) => <div className="rounded-lg border border-gray-800 p-3" key={metric}><div className="text-sm text-gray-200">{metric}</div><div className="mt-2 text-xs text-gray-500">Objetivo {formatPeerValue(value.target_value, metric)}{value.target_atypical ? ' (atípico: posible ganancia no operativa)' : ''} · mediana {peerMedianText(value, metric)} · n={value.peer_sample_size}</div>{(value.excluded_atypical ?? []).length > 0 ? <div className="mt-1 text-xs text-amber-300/80">Fuera de la mediana: {(value.excluded_atypical ?? []).map((ex) => `${ex.ticker} ${ex.value ?? 's/d'}`).join(', ')} - lectura atípica verificable, no benchmark</div> : null}</div>)}</div></Panel>
        <Panel title="Ventajas y desventajas"><p className="text-sm text-gray-400">{peers.analysis?.methodology ? (PEERS_METHODOLOGY_ES[peers.analysis.methodology] ?? peers.analysis.methodology) : 'Sin análisis de comparables persistido.'}</p><p className="mt-3 text-xs text-amber-300">{peers.analysis?.insufficient_data.join(', ')}</p></Panel>
      </div>
    );
  };

  const buildValuationContent = async (): Promise<React.ReactNode> => {
    return <ValuationView valuation={await viewData('valuation')} currency={company.currency} ticker={ticker} />;
  };

  const buildDocumentsContent = async (): Promise<React.ReactNode> => {
    // Conexión 10a: las lecturas de la biblioteca enlazadas a este ticker se
    // piden en paralelo; si la biblioteca falla, la vista sigue sin ellas.
    const [documents, libraryReadings] = await Promise.all([
      viewData('documents'),
      getKnowledgeDocumentsForTicker(ticker).catch(() => null),
    ]);
    return (
      <div className="space-y-6">
        <details className="rounded-lg border border-gray-800 bg-surface-1 p-4" data-testid="add-source">
          <summary className="flex min-h-11 cursor-pointer items-center text-sm font-medium text-teal-300">Añadir fuente (subir archivo o importar URL)</summary>
          <div className="mt-4">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel title="Sube una fuente primaria"><MutationForm action={importResearchDocumentFile} className="grid grid-cols-1 gap-3" successMessage="Documento subido"><input type="hidden" name="ticker" value={ticker} /><Input name="title" placeholder="Título del documento" required /><FileUploadInput name="file" required /><Button type="submit">Subir</Button></MutationForm></Panel>
          <Panel title="Importar desde una URL"><MutationForm action={importResearchDocumentUrl} className="grid grid-cols-1 gap-3" successMessage="Documento importado"><input type="hidden" name="ticker" value={ticker} /><Input name="title" placeholder="Título del documento" required /><Input name="url" type="url" placeholder="https://..." required /><Input name="source_type" placeholder="sec_filing / investor_relations" defaultValue="url" /><Button type="submit">Importar</Button></MutationForm></Panel>
        </div>
          </div>
        </details>
        {/* F249: las fichas enlazan a la fuente primaria cuando el
            documento tiene source_url (filings SEC la traen); sin URL la
            ficha queda como texto, nunca un enlace roto. */}
        <Panel title="Documentos" actions={<Link className="text-sm text-teal-300" href={`/research/${encodeURIComponent(ticker)}/filings`}>Informe frente al año anterior</Link>}>
          {documents.length ? (
            <DocumentsList
              documents={documents.map((document) => ({
                id: document.id,
                title: document.title,
                url: safeHttpUrl(document.source_url),
                tier: etiquetaTierFuente(document.source_tier),
                type: label(document.source_type),
                published: document.published_at ? formatDate(document.published_at) : 'fecha desconocida',
              }))}
            />
          ) : (
            <EmptyState
              action={<EmptyLink href="/research/sources">Importa tu primer documento</EmptyLink>}
              title="Sin documentos ingeridos."
            />
          )}
        </Panel>
        <Panel title="Lecturas de la biblioteca" actions={<Link className="text-sm text-teal-300" href="/knowledge?tab=subir">Añadir a la biblioteca</Link>}>
          {libraryReadings === null ? (
            <EmptyState title="No se pudo cargar la biblioteca ahora mismo." />
          ) : libraryReadings.length ? (
            <ul className="space-y-3">
              {libraryReadings.map((reading) => (
                <li className="rounded-lg border border-gray-800 p-4" key={reading.id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <FileText className="h-4 w-4 text-teal-300" />
                    <Link className="font-medium text-gray-200 underline decoration-gray-700 underline-offset-4 transition hover:text-teal-200" href={libraryDocumentHref(reading.id)}>{reading.title}</Link>
                  </div>
                  <p className="mt-2 text-xs text-gray-500">{reading.author ?? 'Autor desconocido'}{reading.publication_date ? ` · ${formatDate(reading.publication_date)}` : ''}</p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              action={<EmptyLink href="/knowledge">Asigna este ticker a un documento de la biblioteca</EmptyLink>}
              title={`Ningún libro, carta o nota de la biblioteca está enlazado a ${ticker}.`}
            />
          )}
        </Panel>
      </div>
    );
  };

  const buildSourcesSection = async (): Promise<React.ReactNode> => {
    const audits = await viewData('sources');
    return (
      <Panel title="Auditorías de fuentes">
        {audits.length ? (
          <div className="space-y-3">
            {audits.length > 100 ? <p className="text-xs text-gray-500">Se muestran 100 de {formatNumber(audits.length, { maximumFractionDigits: 0 })} auditorías.</p> : null}
            {audits.slice(0, 100).map((audit) => <div className="rounded-lg border border-gray-800 p-4" key={audit.id}><div className="flex flex-wrap gap-2"><Badge>{auditStatusLabel(audit.passed)}</Badge><Badge variant="outline">{auditScoreText(audit.passed, audit.source_coverage_score, String)}</Badge><Badge variant="outline">{audit.thesis_version != null ? `tesis v${audit.thesis_version}` : 'versión de tesis no registrada'}</Badge></div><SourceAuditDetail audit={audit} ticker={ticker} /></div>)}</div>
        ) : (
          <EmptyState
            action={<EmptyLink href={`/research/${encodeURIComponent(ticker)}?view=thesis`}>Genera una tesis para auditar fuentes</EmptyLink>}
            title="Sin auditorías de fuentes persistidas."
          />
        )}
      </Panel>
    );
  };

  const buildChatSection = async (): Promise<React.ReactNode> => {
    return (
      <div className="space-y-6" id="chat-empresa" style={{ scrollMarginTop: '1rem' }}>
        <LegacyChatRedirect ticker={ticker} question={query.chat} />
        <Panel title="Pregunta al Cerebro sobre esta empresa">
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
    if (!terminal) return <EmptyState title="Sin datos del terminal financiero todavía: se cargan con los financieros de la empresa." />;
    return <FinancialTerminalSection metrics={terminalQuery.metrics} periodicity={terminalQuery.periodicity} terminal={terminal} years={terminalQuery.years} />;
  };
  const buildCapitalSection = async (): Promise<React.ReactNode> => <ShareCapitalSection data={await viewData('capital')} ticker={ticker} />;
  const buildSupuestosSection = async (): Promise<React.ReactNode> => <DriverAssumptionsSection assumptions={await viewData('supuestos')} ticker={ticker} />;
  const buildDirectivaSection = async (): Promise<React.ReactNode> => {
    const dashboard = await viewData('directiva');
    if (!dashboard) return <EmptyState title="Sin compromisos de la directiva registrados todavía." />;
    return <ManagementCredibilitySection dashboard={dashboard} ticker={ticker} />;
  };
  const buildLeccionesSection = async (): Promise<React.ReactNode> => <DecisionLessonsSection data={await viewData('lecciones')} ticker={ticker} />;

  type TabSection = { id?: string; title?: string; node: React.ReactNode };

  // Las secciones que no encabezan su pestaña degradan a aviso inline con
  // reintento (nunca a vacío fingido ni a una pestaña entera caída); la de
  // entrada conserva el comportamiento de siempre.
  const optionalSection = async (id: string, title: string, build: () => Promise<React.ReactNode>): Promise<TabSection> => {
    try {
      return { id, title, node: await build() };
    } catch (error) {
      console.warn(`[research] ${ticker} · sección ${id} falló: ${error instanceof Error ? error.message : String(error)}`);
      return { id, title, node: <SectionLoadError retryHref={`${tabHref(ticker, tabOfView(activeView))}#${id}`} title={title} /> };
    }
  };

  // Las seis pestañas y sus secciones, en el orden acordado (opción 1).
  let sections: TabSection[];
  if (activeView === 'overview') {
    sections = [
      { node: await buildOverviewContent() },
      await optionalSection('noticias', 'Noticias', buildNoticiasSection),
    ];
  } else if (activeView === 'thesis') {
    sections = [{ node: await buildThesisContent() }];
  } else if (activeView === 'financials') {
    sections = [
      { id: 'financieros', title: 'Financieros', node: await buildFinancialsContent() },
      await optionalSection('terminal', 'Terminal financiero', buildTerminalSection),
      await optionalSection('dilucion', 'Dilución y recompras', buildCapitalSection),
    ];
  } else if (activeView === 'valuation') {
    sections = [
      { id: 'valoracion', title: 'Valoración', node: await buildValuationContent() },
      await optionalSection('modelo', 'Modelo a largo plazo', buildModelSection),
      await optionalSection('supuestos', 'Supuestos de drivers', buildSupuestosSection),
      await optionalSection('oportunidad', 'Oportunidad de mercado', buildMarketOpportunitySection),
      await optionalSection('comparables', 'Comparables', buildPeersSection),
      await optionalSection('foso', 'Foso', buildMoatSection),
    ];
  } else if (activeView === 'changes') {
    sections = [
      { id: 'cambios', title: 'Cambios y revisiones', node: await buildChangesContent() },
      await optionalSection('superinversores', 'Superinversores', buildHoldersSection),
      await optionalSection('directiva', 'Credibilidad de la directiva', buildDirectivaSection),
      await optionalSection('lecciones', 'Lecciones de decisiones', buildLeccionesSection),
      ...(ticker === 'ASTS' ? [await optionalSection('satellites', 'Satélites AST', buildSatellitesSection)] : []),
    ];
  } else {
    sections = [
      { id: 'documentos', title: 'Documentos', node: await buildDocumentsContent() },
      await optionalSection('fuentes', 'Fuentes', buildSourcesSection),
      { id: 'chat', title: 'Chat con fuentes', node: await buildChatSection() },
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
    ? 'en cartera'
    : companyTypeLabel(company.company_type === 'portfolio_holding' ? 'research_candidate' : company.company_type);

  return (
    <main id="content" tabIndex={-1} className="min-h-screen bg-surface-0 text-gray-100">
      {/* Llegar con ancla (#thesis-change-… desde Inicio, #diario-decisiones):
          el App Router no reintenta el scroll cuando el destino aún no existe
          (Suspense/datos async); este componente sí. */}
      <Suspense fallback={null}><ResearchHashScroll /></Suspense>
      <div className="mx-auto max-w-[1600px]">
        {/* Desde md las migas ya llevan a Research: la flecha solo queda en movil. */}
        <Link className="mb-3 inline-flex min-h-[44px] items-center text-sm text-gray-500 hover:text-gray-200 md:hidden" href="/research"><ArrowLeft className="mr-2 h-4 w-4" />Research</Link>
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
          <div className="scroll-mt-6" id="analistas"><MobileCollapse title="Precios objetivo de analistas"><Suspense fallback={null}><AnalystTargetsSection symbol={quoteSymbolFor({ exchange: company.exchange ?? undefined, currency: company.currency ?? undefined }, ticker) ?? ticker} currency={company.currency} /></Suspense></MobileCollapse></div>
          <MobileCollapse title="Señales DCA: histórico"><Suspense fallback={null}><DcaHitRatesSection ticker={ticker} /></Suspense></MobileCollapse>
        </header>
        {sections.filter((section) => section.id && section.title).length > 1 ? (
          // Sumario local de la pestaña (anclas dentro de la página): nunca
          // otra barra global de menús.
          <nav aria-label="En esta página" className="mb-6 flex flex-wrap gap-x-4 gap-y-1 text-sm">
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
