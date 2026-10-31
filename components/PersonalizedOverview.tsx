'use client';

import { formatCompact, formatUserDateTime, formatMarketDate, formatMoney, formatNumber, formatPercent, formatPrice, isValidCurrencyCode, NA } from '@/lib/format';
import {
    DCF_CANDIDATE_LIMIT,
    dcfScopeNote,
    summarizeDcfProbe,
    type DcfScope,
} from '@/lib/overview/dcf-candidates';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ArrowRight, BellRing, CheckCircle2, Circle, Eye, Gem, Wallet } from 'lucide-react';
import { PortfolioValueBreakdown } from '@/components/portfolio/PortfolioValueBreakdown';
import { DcaLevelChip, useHoldingSignals } from '@/components/portfolio/HoldingSignals';
import { fairValueGapPercent } from '@/lib/portfolio/holding-signals';
import { getPortfolioSummary, type PortfolioHolding, type PortfolioSummary } from '@/lib/actions/portfolio.actions';
import { getHomeWatchlistPreview, getHomeOpportunities } from '@/lib/actions/home-overview.actions';
import { getHomeOverviewBundle, type HomeOverviewBundle } from '@/lib/actions/home-bundle.actions';
import { sectionErrorKey } from '@/lib/section-error';
import {
    getRecentTriggeredAlerts,
    getUserAlerts,
    type Alert,
    type TriggeredAlertDelivery,
} from '@/lib/actions/alerts.actions';
import { holdingDisplayMode } from '@/lib/portfolio/holding-display';
import { alertCardDestination, alertThesisHref } from '@/lib/alerts/card-destination';
import { alertCardCopy, alertSummaryIsSourceHeadline } from '@/lib/alerts/card-copy';
import { ExternalNewsHeadline } from '@/components/research/ExternalNewsHeadline';
import { useLocale, useT } from '@/lib/i18n/client';
import { t as legacyT } from '@/lib/i18n/t';
import { buildPortfolioInsight } from '@/lib/portfolio-insight';
import HomeAttention from '@/components/HomeAttention';

interface PersonalizedOverviewProps {
    userId: string;
    /** Bloque de servidor que se pinta entre Alertas y Watchlist (calendario). */
    afterAlerts?: ReactNode;
}

interface WatchlistItem {
    symbol: string;
    name: string;
    // null = sin cotización disponible: nunca se fabrica un 0.
    price: number | null;
    currency: string | null;
    changePercent: number | null;
    // F358: frescura del precio; un cierre se etiqueta con su fecha si la fuente la da.
    priceKind: 'live' | 'close' | null;
    priceAsOf: string | null;
}

interface UndervaluedStock {
    symbol: string;
    name: string;
    price: number;
    /** Divisa del LISTADO real (master), no del ticker desnudo: null = N/D. */
    currency: string | null;
    fairValue: number;
    upside: number;
    /** true = el DCF no es publicable (inputs sin trazabilidad datada):
     *  la ficha lo muestra como orientacion del motor, no como valoracion final. */
    orientation?: boolean;
    /** Procedencia del valor justo único (misma cifra que la watchlist). */
    fairValueLabel?: string;
    fairValueAsOf?: string | null;
}

/** Valor justo único de una posición en el inicio: margen frente al precio y su fuente. */
function HomeFairValueHint({ holding, signals }: { holding: PortfolioHolding; signals: ReturnType<typeof useHoldingSignals> }) {
    const t = useT();
    if (signals === null) return null;
    const fair = signals.fairValues[holding.symbol.toUpperCase()];
    if (!fair) return <span className="text-[11px] text-gray-500">{t('home.fair.none')}</span>;
    const gap = fairValueGapPercent(holding.currentPrice, holding.nativeCurrency, fair);
    return (
        <span className="whitespace-nowrap text-[11px] text-gray-400" title={t('home.fair.title', { label: fair.label })}>
            VJ {gap !== null ? formatPercent(gap, { fromRatio: false, digits: 0, signDisplay: 'always' }) : formatNumber(fair.value)}
            <span className="text-gray-500"> · {fair.source === 'tesis' ? t('home.fair.source.tesis') : fair.source === 'motor' ? t('home.fair.source.motor') : t('home.fair.source.orient')}</span>
        </span>
    );
}

/** El universo del screener es todo lo que devuelve /api/screeners/real por
 *  encima de este market cap. La tarjeta solo prueba las primeras
 *  DCF_CANDIDATE_LIMIT candidatas y lo dice (F65): no puede hablar en nombre
 *  de todo el universo. Antes se filtraba por `sector: 'Technology'`
 *  (duplicaba /screener?sector=Technology sin decirlo). */
const MIN_MARKET_CAP = 10_000_000_000;

/** La watchlist del inicio es una MIRADA: 3 filas y el resto vive en
 *  /watchlist, que es la página de la lista completa. Antes pintaba 5 filas
 *  sin decir cuántas quedaban fuera. */
const WATCHLIST_PREVIEW_LIMIT = 3;

/** Fichas de oportunidad que caben en la mirada del inicio. El bloque es el
 *  más caro (2 server actions por candidata) y la lista completa, con filtros,
 *  es /screener: 3 reachan para decidir por dónde mirar. Cuando se recorta se
 *  declara cuántas se dejan fuera. */
const OPPORTUNITY_TILE_LIMIT = 3;

/**
 * Secciones de reintento independientes: pulsar «Reintentar» en la tarjeta de
 * alertas ya no vuelve a pedir cartera, watchlist y los DCF (antes bastaba un
 * fallo de índices para relanzar las ~23 llamadas del inicio).
 */
type SectionKey = 'portfolio' | 'alerts' | 'watchlist' | 'opportunities';

const EMPTY_RETRY_TOKENS: Record<SectionKey, number> = {
    portfolio: 0,
    alerts: 0,
    watchlist: 0,
    opportunities: 0,
};

/**
 * Estado de carga por sección con el patrón de components/LoadingState.tsx: el
 * texto vive en un nodo `sr-only` y el esqueleto va `aria-hidden`. Antes cada
 * sección escribía su propio `role="status"` con `aria-label` (que no se
 * anuncia) y cuatro variantes distintas de `animate-pulse`.
 */
/**
 * Primeros pasos (auditoría UX 2026-10-27): con la cartera vacía, la tarjeta
 * «Tu cartera hoy» era un «Comienza tu viaje» genérico y el usuario nuevo no
 * sabía por dónde empezar. Ocupa el mismo hueco que ya reservaba el esqueleto
 * de la tarjeta (no inserta nada encima del resto, así que no añade saltos de
 * maquetación) y marca como hecho lo que ya ha hecho.
 */
function FirstSteps({ watchlistCount }: { watchlistCount: number | null }) {
    const t = useT();
    const watchlistDone = (watchlistCount ?? 0) > 0;
    const stepClass = 'flex min-h-[44px] items-start gap-3 rounded-lg border border-gray-700/40 bg-gray-900/30 p-3';
    return (
        <div>
            <h3 className="text-base font-semibold text-white">{t('home.steps.title')}</h3>
            <p className="mt-1 text-sm text-gray-400">{t('home.steps.subtitle')}</p>
            <ol className="mt-4 space-y-2">
                <li className={stepClass}>
                    {watchlistDone
                        ? <CheckCircle2 aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-teal-400" />
                        : <Circle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-gray-500" />}
                    <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-100">{t('home.steps.followTitle')}</p>
                        <p className="text-xs text-gray-400">
                            {watchlistDone
                                ? t('home.steps.followDone', { count: watchlistCount ?? 0, unit: watchlistCount === 1 ? t('home.steps.company') : t('home.steps.companies') })
                                : t('home.steps.followTodo')}
                        </p>
                    </div>
                    <Link href={watchlistDone ? '/watchlist' : '/watchlist?anadir=1'} className="inline-flex min-h-[44px] shrink-0 items-center text-sm text-teal-300 hover:text-teal-200">
                        {watchlistDone ? t('home.steps.view') : t('home.steps.add')}
                        <span className="sr-only">{t('home.steps.watchlistSr')}</span>
                    </Link>
                </li>
                <li className={stepClass}>
                    <Circle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-gray-500" />
                    <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-100">{t('home.steps.buyTitle')}</p>
                        <p className="text-xs text-gray-400">{t('home.steps.buyBody')}</p>
                    </div>
                    <Link href="/portfolio?anadir=1" className="inline-flex min-h-[44px] shrink-0 items-center text-sm text-teal-300 hover:text-teal-200">
                        {t('home.steps.add')}<span className="sr-only">{t('home.steps.investmentSr')}</span>
                    </Link>
                </li>
                <li className={stepClass}>
                    <Circle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-gray-500" />
                    <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-100">{t('home.steps.brainTitle')}</p>
                        <p className="text-xs text-gray-400">{t('home.steps.brainBody')}</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => window.dispatchEvent(new Event('gerarai:open-brain'))}
                        className="inline-flex min-h-[44px] shrink-0 items-center text-sm text-teal-300 hover:text-teal-200"
                    >
                        {t('home.steps.open')}<span className="sr-only">{t('home.steps.brainSr')}</span>
                    </button>
                </li>
            </ol>
        </div>
    );
}

function SectionSkeleton({ rows = 3, className }: { rows?: number; className?: string }) {
    const t = useT();
    return (
        <div className={className}>
            <span className="sr-only" role="status">{t('common.states.loading')}</span>
            <div aria-hidden="true" className="space-y-3">
                {Array.from({ length: rows }).map((_, index) => (
                    <Skeleton className="h-12 w-full" key={index} />
                ))}
            </div>
        </div>
    );
}



/**
 * Esqueleto de «Tu cartera hoy» con la MISMA estructura que la tarjeta con
 * posiciones (desglose, fila de G/P, nota, rejilla de hasta 4 posiciones y
 * enlace) y las mismas clases de rejilla, para que el hueco reservado crezca
 * igual por breakpoint. Con 5 filas fijas (≈330 px) la tarjeta real medía
 * ≈850 px a 375 px y ≈580 px en escritorio, y empujaba el resto del inicio:
 * CLS 0,16 en móvil (barrido del 29-oct-2026).
 */
function PortfolioCardSkeleton() {
    const t = useT();
    return (
        <div data-testid="portfolio-skeleton">
            <span className="sr-only" role="status">{t('common.states.loading')}</span>
            <div aria-hidden="true" className="space-y-5">
                <div className="rounded-xl border border-gray-700/50 bg-gray-900/60 p-4">
                    <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
                        {Array.from({ length: 4 }).map((_, index) => (
                            <div key={index}>
                                <Skeleton className="h-5 w-28" />
                                <Skeleton className="mt-1 h-7 w-32" />
                            </div>
                        ))}
                    </div>
                </div>
                <Skeleton className="h-10 w-full sm:h-5" />
                <Skeleton className="h-4 w-2/3" />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {Array.from({ length: 4 }).map((_, index) => (
                        <Skeleton className="h-14 w-full sm:h-[4.5rem]" key={index} />
                    ))}
                </div>
                <Skeleton className="h-11 w-40" />
            </div>
        </div>
    );
}

function InlineSectionError({ message, onRetry }: { message: string; onRetry: () => void }) {
    const t = useT();
    const text = message.startsWith('ui.sectionError.') ? t(message as Parameters<typeof t>[0]) : message;
    return (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
            <span>{text}</span>
            <button type="button" onClick={onRetry} className="underline hover:text-amber-100">{t('common.actions.retry')}</button>
        </div>
    );
}

/** El backend devuelve la severidad en inglés ("high", "critical"): sin
 *  traducirla se colaba copy en inglés en la UI. */
const SEVERITY_KEYS = {
    critical: 'home.severity.critical',
    high: 'home.severity.high',
    medium: 'home.severity.medium',
    low: 'home.severity.low',
    info: 'home.severity.info',
} as const;

/** La cabecera de la alerta lleva la fecha del hecho; si es el mismo día que
 *  la hora de entrega que se ve justo al lado, se omite para no repetirla. El
 *  sufijo exacto lo devuelve card-copy (ya traducido y con el formato del
 *  idioma activo): nada de parsear meses en español con regex. */
function alertHeading(heading: string, dateSuffix: string | null, createdAt: string, locale: string): string {
    if (!dateSuffix || !heading.endsWith(dateSuffix)) return heading;
    const created = new Date(createdAt);
    if (Number.isNaN(created.getTime())) return heading;
    const sameDay = new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'es-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Madrid' }).format(created);
    return dateSuffix.endsWith(sameDay) ? heading.slice(0, -dateSuffix.length) : heading;
}

/** Una regla de alerta en una línea legible: "AAPL: precio por encima de 200". */
function alertRuleLabel(alert: Alert): string {
    const labels: Record<Alert['type'], string> = {
        price_above: legacyT('alerts.types.priceAbove'),
        price_below: legacyT('alerts.types.priceBelow'),
        price_change: legacyT('alerts.types.priceChange'),
        news: legacyT('alerts.types.news'),
        earnings: legacyT('alerts.types.earnings'),
    };
    if (alert.type === 'news' || alert.type === 'earnings') return `${alert.symbol}: ${labels[alert.type]}`;
    const value = typeof alert.condition.value === 'number'
        ? formatNumber(alert.condition.value, { maximumFractionDigits: 2 })
        : String(alert.condition.value);
    return `${alert.symbol}: ${labels[alert.type]} ${value}`;
}

/** Envuelve una lectura para que un fallo aislado no tumbe la sección: el
 *  resultado llega siempre con su mensaje de error al lado. */
function settle<T>(promise: Promise<T>, fallback: T): Promise<{ data: T; error: string | null }> {
    return promise
        .then((data) => ({ data, error: null as string | null }))
        .catch((error) => ({ data: fallback, error: sectionErrorKey(error) }));
}

export default function PersonalizedOverview({ userId, afterAlerts }: PersonalizedOverviewProps) {
    const t = useT();
    const locale = useLocale();
    const [retryTokens, setRetryTokens] = useState<Record<SectionKey, number>>(EMPTY_RETRY_TOKENS);
    const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null);
    const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
    const [watchlistTotal, setWatchlistTotal] = useState(0);
    const [alerts, setAlerts] = useState<Alert[]>([]);
    const [triggeredAlerts, setTriggeredAlerts] = useState<TriggeredAlertDelivery[]>([]);
    const [opportunities, setOpportunities] = useState<UndervaluedStock[]>([]);
    const [dcfScope, setDcfScope] = useState<DcfScope | null>(null);
    const [portfolioLoading, setPortfolioLoading] = useState(true);
    const [watchlistLoading, setWatchlistLoading] = useState(true);
    const [opportunitiesLoading, setOpportunitiesLoading] = useState(true);
    const [alertsLoading, setAlertsLoading] = useState(true);
    const [portfolioError, setPortfolioError] = useState<string | null>(null);
    const [watchlistError, setWatchlistError] = useState<string | null>(null);
    const [opportunitiesError, setOpportunitiesError] = useState<string | null>(null);
    const [alertsError, setAlertsError] = useState<string | null>(null);

    const retrySection = (section: SectionKey) =>
        setRetryTokens((tokens) => ({ ...tokens, [section]: tokens[section] + 1 }));

    // Primera carga: las TRES lecturas rápidas en UNA server action (Next
    // ejecuta en serie las server actions de un cliente). Oportunidades NO
    // va en ese POST: su sondeo DCF cotiza con proveedores externos en
    // síncrono (~7 s medidos en prod, 31-oct) y, al compartir promesa,
    // hacía esperar a cartera, alertas y watchlist esos ~7 s antes de
    // pintar. Se pide aparte, tras el primer pintado (debajo del pliegue).
    // Cada sección toma su parte; los «Reintentar» usan la lectura suelta.
    const bundleRef = useRef<{ userId: string; promise: Promise<HomeOverviewBundle> } | null>(null);
    const firstLoad = useCallback(<K extends keyof HomeOverviewBundle>(
        key: K,
        fallback: HomeOverviewBundle[K]['data'],
    ): Promise<{ data: HomeOverviewBundle[K]['data']; error: string | null }> => {
        if (!bundleRef.current || bundleRef.current.userId !== userId) {
            bundleRef.current = {
                userId,
                promise: getHomeOverviewBundle(userId, {
                    watchlistLimit: WATCHLIST_PREVIEW_LIMIT,
                }),
            };
        }
        return bundleRef.current.promise
            .then((bundle) => bundle[key])
            .catch((error) => ({ data: fallback, error: sectionErrorKey(error) }));
    }, [userId]);

    // Una sección, un disparador: cada «Reintentar» vuelve a pedir solo su
    // lectura (antes los cuatro reintentos relanzaban el loadData completo).
    useEffect(() => {
        let active = true;

        const load = async () => {
            setPortfolioLoading(true);
            setPortfolioError(null);
            const result = retryTokens.portfolio === 0
                ? await firstLoad('portfolio', null)
                : await settle(getPortfolioSummary(userId), null as PortfolioSummary | null);
            if (!active) return;
            setPortfolioSummary(result.data);
            setPortfolioLoading(false);
            setPortfolioError(result.error);
        };

        void load();
        return () => {
            active = false;
        };
    }, [userId, retryTokens.portfolio, firstLoad]);

    useEffect(() => {
        let active = true;

        const load = async () => {
            setAlertsLoading(true);
            setAlertsError(null);
            const result = retryTokens.alerts === 0
                ? await firstLoad('alerts', { rules: [], triggered: [] })
                : await settle(
                    Promise.all([getUserAlerts(), getRecentTriggeredAlerts(3)]).then(([rules, triggered]) => ({ rules, triggered })),
                    { rules: [] as Alert[], triggered: [] as TriggeredAlertDelivery[] },
                );
            if (!active) return;
            setAlerts(result.data.rules);
            setTriggeredAlerts(result.data.triggered);
            setAlertsLoading(false);
            setAlertsError(result.error);
        };

        void load();
        return () => {
            active = false;
        };
    }, [retryTokens.alerts, firstLoad]);

    // Solo se cotizan las primeras WATCHLIST_PREVIEW_LIMIT entradas: el resto
    // son un contador y un enlace a /watchlist, no filas anónimas.
    useEffect(() => {
        let active = true;

        const load = async () => {
            setWatchlistLoading(true);
            setWatchlistError(null);
            const result = retryTokens.watchlist === 0
                ? await firstLoad('watchlist', { unavailable: false, total: 0, items: [] })
                : await settle(
                    getHomeWatchlistPreview(WATCHLIST_PREVIEW_LIMIT).then((preview) => {
                        if (preview.unavailable) throw new Error('No se pudo cargar la watchlist');
                        return preview;
                    }),
                    { unavailable: false, total: 0, items: [] as WatchlistItem[] },
                );
            if (!active) return;
            if (result.error) {
                setWatchlistTotal(0);
                setWatchlist([]);
                setWatchlistLoading(false);
                setWatchlistError(result.error);
                return;
            }
            setWatchlistTotal(result.data.total);
            const items = result.data.items;
            if (!active) return;
            setWatchlist(items);
            setWatchlistLoading(false);
        };

        void load();
        return () => {
            active = false;
        };
    }, [retryTokens.watchlist, firstLoad]);

    useEffect(() => {
        let active = true;

        const load = async () => {
            setOpportunitiesLoading(true);
            setOpportunitiesError(null);
            // Siempre lectura propia, también en primera carga: no forma
            // parte del bundle del primer pintado (ver nota sobre firstLoad).
            const probe = await settle(
                getHomeOpportunities({
                    marketCapMoreThan: MIN_MARKET_CAP,
                    limit: 10,
                    candidateLimit: DCF_CANDIDATE_LIMIT,
                }),
                [] as Awaited<ReturnType<typeof getHomeOpportunities>>,
            );
            if (!active) return;
            if (probe.error) {
                setOpportunities([]);
                setDcfScope(null);
                setOpportunitiesLoading(false);
                setOpportunitiesError(probe.error);
                return;
            }
            // F65: se prueban solo las primeras candidatas y se cuenta cuantas
            // se pudieron evaluar; un DCF fallido no equivale a "sin potencial".
            const results = probe.data;
            if (!active) return;
            // La lista completa se conserva en el estado para poder DECLARAR
            // cuántas fichas se recorta por el tope de la mirada.
            setOpportunities(results
                .map((result) => result.opportunity)
                .filter((op): op is UndervaluedStock => op !== null)
                .sort((a, b) => b.upside - a.upside));
            setDcfScope(summarizeDcfProbe(results));
            setOpportunitiesLoading(false);
        };

        void load();
        return () => {
            active = false;
        };
    }, [retryTokens.opportunities, firstLoad]);

    // Derivados memorizados: evita reordenar el estado en cada render
    // (.sort() mutaba el array del estado) y recalcula solo si cambian los datos.
    const sortedHoldings = useMemo(() => {
        if (!portfolioSummary) return [];
        return [...portfolioSummary.holdings]
            .sort((a, b) => {
                const aCost = holdingDisplayMode(a) === 'gain';
                const bCost = holdingDisplayMode(b) === 'gain';
                if (aCost !== bCost) return aCost ? -1 : 1;
                return aCost ? Math.abs(b.gainPercent) - Math.abs(a.gainPercent) : b.value - a.value;
            })
            .slice(0, 4);
    }, [portfolioSummary]);

    // Nivel DCA y valor justo único de las posiciones que se ven en el inicio.
    const holdingSignals = useHoldingSignals(sortedHoldings.map((h) => h.symbol));

    /** Frase "tu cartera en una línea": derivada solo del resumen, nunca
     *  del waterfall de oportunidades (F38). */
    const insight = useMemo(() => buildPortfolioInsight(portfolioSummary), [portfolioSummary]);

    /** Mayor variación absoluta desde la compra, no cambio de hoy ni su causa.
     *  Sin base de coste no hay dato para elegir esta posición. */
    const topMover = useMemo<PortfolioHolding | null>(() => {
        const conCoste = (portfolioSummary?.holdings ?? []).filter((h) => h.cost > 0 && !h.fxMissing && !h.quoteMissing);
        if (!conCoste.length) return null;
        return conCoste.reduce((a, b) => Math.abs(b.gainPercent) > Math.abs(a.gainPercent) ? b : a);
    }, [portfolioSummary]);

    const visibleOpportunities = opportunities.slice(0, OPPORTUNITY_TILE_LIMIT);

    return (
        <div className="space-y-6">
            {/* Encabezado: el h1 es el dato accionable del día, no un saludo. */}
            <div>
                <p className="text-sm font-semibold uppercase text-teal-300">{t('home.overview.kicker')}</p>
                <h1 className="mt-1 text-2xl font-bold break-words text-gray-100 sm:text-3xl">{t('home.overview.title')}</h1>
            </div>

            {/* 1 · Cartera hoy. La frase «tu cartera en una línea» vive DENTRO de
                esta tarjeta (antes era una tarjeta suelta con el mismo
                portfolioSummary detrás): leer valor y frase juntos es una decisión,
                no dos. Si la lectura de cartera falla, la tarjeta es la que muestra
                el error y su reintento, porque es la dueña del dato. */}
            <Card className="bg-gray-800/50 border-gray-700">
                <CardHeader className="flex flex-row items-center justify-between pb-2 border-b border-gray-700/50">
                    <CardTitle as="h2" className="text-lg text-gray-100 flex items-center gap-2">
                        <Wallet aria-hidden="true" className="h-5 w-5 text-blue-400" />
                        {t('home.portfolio.title')}
                    </CardTitle>
                    <Link href="/portfolio" className="inline-flex min-h-[44px] items-center gap-1 px-2 -mr-2 text-blue-400 hover:text-blue-300 text-sm transition-colors">
                        <span className="whitespace-nowrap">{t('home.portfolio.details')}</span> <ArrowRight aria-hidden="true" className="w-4 h-4 shrink-0" />
                    </Link>
                </CardHeader>
                <CardContent className="pt-4">
                    {portfolioLoading ? (
                        // Misma estructura que la tarjeta con posiciones: el hueco
                        // reservado crece igual por breakpoint (CLS móvil).
                        <PortfolioCardSkeleton />
                    ) : portfolioError ? (
                        <InlineSectionError message={portfolioError} onRetry={() => retrySection('portfolio')} />
                    ) : portfolioSummary && portfolioSummary.holdings.length > 0 ? (
                        <div className="space-y-5">
                            <PortfolioValueBreakdown summary={portfolioSummary} />
                            <div className="flex items-center justify-between gap-3 text-sm">
                                <span className="text-gray-400">{t('home.portfolio.gainLoss')}</span>
                                <span className={`font-semibold ${insight.kind !== 'movement' ? 'text-gray-500' : portfolioSummary.totalGainPercent >= 0 ? 'text-good' : 'text-bad'}`}>
                                    {insight.kind !== 'movement' ? 'N/D' : formatPercent(portfolioSummary.totalGainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                                </span>
                            </div>
                            <p className="text-xs text-gray-400">{t('home.portfolio.weightsNote')}</p>
                            {insight.kind === 'empty' && (
                                <p className="text-xs text-gray-400">{t('home.portfolio.empty')}</p>
                            )}
                            {insight.kind === 'no-cost-basis' && (
                                <p className="text-xs text-gray-400">{t('home.portfolio.noCostBasis')}</p>
                            )}
                            {insight.kind === 'movement' && insight.partial && (
                                <p className="text-xs text-gray-400">{t('home.portfolio.partial')}</p>
                            )}
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                {sortedHoldings
                                    .map((h) => (
                                        <Link
                                            key={h.symbol}
                                            href={`/research/${h.symbol}`}
                                            className="flex min-h-[44px] flex-wrap items-center justify-between gap-3 p-3 bg-gray-800 rounded-lg hover:bg-gray-700 transition-colors border border-gray-700/30"
                                        >
                                            <span className="flex min-w-0 flex-1 flex-col gap-1">
                                                <span className="flex min-w-0 items-center justify-between gap-3">
                                                    <span className="text-white font-semibold">{h.symbol}</span>
                                                    {holdingDisplayMode(h) === 'gain' ? (
                                                        <span className={`shrink-0 font-mono ${h.gainPercent >= 0 ? 'text-good' : 'text-bad'}`}>
                                                            {formatPercent(h.gainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                                                        </span>
                                                    ) : holdingDisplayMode(h) === 'value' && isValidCurrencyCode(h.baseCurrency) ? (
                                                        // Sin base de coste no hay rentabilidad (N/D), pero el valor y el peso
                                                        // salen de la cotización y se muestran con su divisa.
                                                        <span className="shrink-0 text-right font-mono text-gray-300">
                                                            {formatMoney(h.value, h.baseCurrency)}
                                                            {portfolioSummary && portfolioSummary.equityValue > 0
                                                                ? `\u00a0\u00b7 ${formatPercent((h.value / portfolioSummary.equityValue) * 100, { fromRatio: false, digits: 1 })}`
                                                                : ''}
                                                        </span>
                                                    ) : (
                                                        <span className="shrink-0 font-mono text-gray-500">{NA}</span>
                                                    )}
                                                </span>
                                                <span className="flex flex-wrap items-center gap-1">
                                                    <DcaLevelChip symbol={h.symbol} signals={holdingSignals} />
                                                    <HomeFairValueHint holding={h} signals={holdingSignals} />
                                                </span>
                                            </span>
                                        </Link>
                                    ))}
                            </div>
                            <Link
                                href={topMover ? `/research/${topMover.symbol}?view=changes` : '/portfolio'}
                                className="inline-flex min-h-[44px] items-center gap-1 text-sm text-teal-300 hover:text-teal-200"
                            >
                                <span className="min-w-0">
                                    {topMover ? t('home.portfolio.reviewMover', { symbol: topMover.symbol }) : t('home.portfolio.reviewAll')}
                                </span>
                                <ArrowRight aria-hidden="true" className="w-4 h-4 shrink-0" />
                            </Link>
                        </div>
                    ) : (
                        <FirstSteps watchlistCount={watchlistLoading || watchlistError ? null : watchlistTotal} />
                    )}
                </CardContent>
            </Card>

            <HomeAttention />

            {/* 2 · Alertas: la sección que faltaba en el inicio pese a existir /alerts. */}
            <Card className="bg-gray-800/50 border-gray-700">
                <CardHeader className="flex flex-row items-center justify-between pb-2 border-b border-gray-700/50">
                    <CardTitle as="h2" className="text-lg text-gray-100 flex items-center gap-2">
                        <BellRing aria-hidden="true" className="h-5 w-5 text-amber-400" />
                        {t('home.alerts.title')}
                    </CardTitle>
                    <Link href="/alerts" className="inline-flex min-h-[44px] items-center gap-1 px-2 -mr-2 text-amber-400 hover:text-amber-300 text-sm transition-colors">
                        <span className="whitespace-nowrap">{t('home.alerts.manage')}</span> <ArrowRight aria-hidden="true" className="w-4 h-4 shrink-0" />
                    </Link>
                </CardHeader>
                <CardContent className="pt-4">
                    {alertsLoading ? (
                        <SectionSkeleton rows={2} />
                    ) : alertsError ? (
                        <InlineSectionError message={alertsError} onRetry={() => retrySection('alerts')} />
                    ) : triggeredAlerts.length > 0 ? (
                        <div className="space-y-3">
                            {triggeredAlerts.map((item) => {
                                // F300-extensión: la tarjeta entera navega con el patrón
                                // de enlace estirado (el CTA principal lleva
                                // after:absolute after:inset-0 sobre la tarjeta
                                // `relative`); el CTA secundario queda por encima con
                                // relative z-10 y conserva su destino. Sin enlaces
                                // anidados ni roles duplicados.
                                const destination = alertCardDestination(item);
                                const copy = alertCardCopy(item, t, locale);
                                return (
                                <article
                                    className={`min-w-0 rounded-lg border p-3 ${destination ? 'relative border-gray-700/50 bg-gray-900/50 transition-colors hover:border-teal-700/60 hover:bg-gray-900' : 'border-gray-700/50 bg-gray-900/50'}`}
                                    key={item.id}
                                >
                                    <div className="flex flex-wrap items-center gap-2">
                                        {(item.severity === 'critical' || item.severity === 'high') && <Badge variant="outline">{t(SEVERITY_KEYS[item.severity as keyof typeof SEVERITY_KEYS] ?? 'home.severity.info')}</Badge>}
                                        <span className="text-xs text-gray-500">{formatUserDateTime(item.createdAt)}</span>
                                    </div>
                                    <p className="mt-2 text-sm break-words font-semibold text-gray-100">{alertHeading(copy.heading, copy.dateSuffix, item.createdAt, locale)}</p>
                                    {/* tracked_news lleva el titular crudo de la fuente: misma
                                        traducción bajo demanda que en /alerts (#1493). */}
                                    {alertSummaryIsSourceHeadline(item) ? (
                                        <ExternalNewsHeadline headline={copy.summary} url={item.sourceUrl} className="mt-1 text-sm break-words text-gray-300" />
                                    ) : (
                                        <p className="mt-1 text-sm break-words text-gray-300">{copy.summary}</p>
                                    )}
                                    {!item.alert_type.includes('news') && <details className="relative z-10 mt-2 break-words text-xs text-gray-400"><summary className="min-h-11 cursor-pointer py-2 text-teal-300 sm:min-h-10">{t('home.alerts.originalNotice')}</summary><p className="whitespace-pre-wrap">{copy.technical}</p></details>}
                                    {(item.ticker || item.sourceUrl) && (
                                        <span className="mt-2 inline-flex flex-wrap gap-3">
                                            {item.ticker && (
                                                <Link
                                                    className="inline-flex min-h-[44px] items-center text-xs text-teal-400 after:absolute after:inset-0 after:rounded-lg after:content-[''] hover:text-teal-300 hover:underline"
                                                    href={alertThesisHref(item.ticker)}
                                                >
                                                    {t('home.alerts.reviewThesis', { symbol: item.ticker })}
                                                </Link>
                                            )}
                                            {item.sourceUrl && (
                                                <a
                                                    className={`inline-flex min-h-[44px] items-center text-xs text-teal-400 hover:text-teal-300 hover:underline ${item.ticker ? 'relative z-10' : "after:absolute after:inset-0 after:rounded-lg after:content-['']"}`}
                                                    href={item.sourceUrl}
                                                    rel="noopener noreferrer"
                                                    target="_blank"
                                                >
                                                    {t('home.alerts.openDocument')}
                                                </a>
                                            )}
                                        </span>
                                    )}
                                </article>
                                );
                            })}
                            <p className="text-xs text-gray-500">
                                {`${alerts.length === 1 ? t('home.alerts.rulesActiveOne') : t('home.alerts.rulesActiveOther', { n: alerts.length })} · ${t('home.alerts.evaluated')}`}
                            </p>
                        </div>
                    ) : alerts.length > 0 ? (
                        <div className="space-y-2">
                            {alerts.slice(0, 3).map((alert) => (
                                <Link
                                    href="/alerts"
                                    className="block min-w-0 break-words rounded px-1 -mx-1 py-0.5 text-sm text-gray-300 transition-colors hover:text-amber-300"
                                    key={alert._id}
                                >
                                    {alertRuleLabel(alert)}
                                </Link>
                            ))}
                            <p className="text-xs text-gray-500">
                                {`${alerts.length === 1 ? t('home.alerts.rulesActiveOne') : t('home.alerts.rulesActiveOther', { n: alerts.length })} · ${t('home.alerts.noneTriggered')}`}
                            </p>
                        </div>
                    ) : (
                        <div className="text-center py-6">
                            <p className="text-gray-400 text-sm">{t('common.states.noAlerts')}</p>
                            <p className="text-gray-500 text-sm mt-2">{t('common.states.noAlertsHint')}</p>
                            <Link href="/alerts" className="mt-3 inline-flex min-h-[44px] items-center justify-center rounded-lg border border-teal-400/20 px-5 text-sm text-teal-400 transition-colors hover:text-teal-300">
                                Crear la primera alerta
                            </Link>
                        </div>
                    )}
                </CardContent>
            </Card>

            {afterAlerts}

            {/* 3 · Watchlist: mirada de 3 filas. La lista completa es /watchlist. */}
            <Card className="bg-gray-800/50 border-gray-700">
                <CardHeader className="flex flex-row items-center justify-between pb-2 border-b border-gray-700/50">
                    <CardTitle as="h2" className="text-lg text-gray-100 flex items-center gap-2">
                        <Eye aria-hidden="true" className="h-5 w-5 text-yellow-400" />
                        {t('home.watchlist.recent')}
                    </CardTitle>
                    <Link href="/watchlist" className="inline-flex min-h-[44px] items-center gap-1 px-2 -mr-2 text-yellow-400 hover:text-yellow-300 text-sm transition-colors">
                        <span className="whitespace-nowrap">{t('home.watchlist.viewAll')}</span> <ArrowRight aria-hidden="true" className="w-4 h-4 shrink-0" />
                    </Link>
                </CardHeader>
                <CardContent className="pt-4">
                    {watchlistLoading ? (
                        <SectionSkeleton rows={3} />
                    ) : watchlistError ? (
                        <InlineSectionError message={watchlistError} onRetry={() => retrySection('watchlist')} />
                    ) : watchlist.length > 0 ? (
                        <div className="space-y-3">
                            <div className="space-y-1">
                                {watchlist.map((stock) => (
                                    <Link
                                        key={stock.symbol}
                                        href={`/research/${stock.symbol}`}
                                        className="flex min-h-[44px] items-center justify-between gap-2 p-3 bg-gray-900/30 rounded-lg hover:bg-gray-800/80 transition-colors group"
                                    >
                                        <div className="flex min-w-0 items-center gap-3">
                                            <div className="min-w-0">
                                                <span className="block truncate text-white font-medium group-hover:text-yellow-400 transition-colors">{stock.symbol}</span>
                                                <p className="block truncate text-xs text-gray-500" title={stock.name}>{stock.name}</p>
                                            </div>
                                        </div>
                                        <div className="shrink-0 text-right">
                                            {stock.price != null ? (
                                                <>
                                                    <div className="text-white font-mono">{isValidCurrencyCode(stock.currency) ? formatPrice(stock.price, stock.currency) : formatNumber(stock.price)}</div>
                                                    {stock.priceKind === 'close' && (
                                                        <div className="text-[10px] text-gray-500">{stock.priceAsOf ? t('home.watchlist.close', { date: formatMarketDate(stock.priceAsOf) }) : t('home.watchlist.closeNoDate')}</div>
                                                    )}
                                                    {stock.changePercent != null && (
                                                        <div className={`text-xs ${stock.changePercent >= 0 ? 'text-good' : 'text-bad'}`}>
                                                            {formatPercent(stock.changePercent, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                                                        </div>
                                                    )}
                                                </>
                                            ) : (
                                                <>
                                                    <div className="font-mono text-gray-500" title={t('home.watchlist.noQuote')}>&mdash;</div>
                                                    <div className="text-[10px] uppercase tracking-wide text-gray-500">{t('home.watchlist.noData')}</div>
                                                </>
                                            )}
                                        </div>
                                    </Link>
                                ))}
                            </div>
                            <p className="text-xs text-gray-500">
                                {watchlistTotal > watchlist.length ? t('home.watchlist.lastNOfTotal', { n: watchlist.length, total: watchlistTotal }) : t('home.watchlist.totalCount', { total: watchlistTotal })} ·{' '}
                                <Link href="/watchlist" className="inline-flex min-h-[44px] items-center text-yellow-400 hover:underline">
                                    ver la lista completa
                                </Link>
                            </p>
                        </div>
                    ) : (
                        <div className="text-center py-8">
                            <p className="text-gray-400 text-sm">{t('home.watchlist.empty')}</p>
                            {/* /watchlist tiene su propio «Añadir empresa» (con alta por
                                símbolo): es el destino directo, sin pasar por /search. */}
                            <Link href="/watchlist" className="mt-2 inline-flex min-h-[44px] items-center justify-center rounded-lg border border-yellow-400/30 px-4 text-sm text-yellow-400 hover:bg-yellow-950/30">
                                Añadir empresas
                            </Link>
                        </div>
                    )}
                </CardContent>
            </Card>

            {/* 4 · Oportunidades por valor intrínseco. Mientras carga, o sin candidatas y sin error, el bloque no se pinta (así no aparece y desaparece): una tarjeta que solo dice «ninguna» no aporta. */}
            {!opportunitiesLoading && (opportunitiesError || opportunities.length > 0) && (
            <Card className="bg-gray-800/50 border-gray-700">
                <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-x-2 pb-2 border-b border-gray-700/50">
                    <CardTitle as="h2" className="text-lg text-gray-100 flex items-center gap-2">
                        <Gem aria-hidden="true" className="h-5 w-5 text-purple-400" />
                        {t('home.opportunities.title')}
                    </CardTitle>
                    <Link href="/screener" className="inline-flex min-h-[44px] items-center gap-1 px-2 -mr-2 text-purple-400 hover:text-purple-300 text-sm transition-colors">
                        <span className="whitespace-nowrap">{t('home.opportunities.refine')}</span> <ArrowRight aria-hidden="true" className="w-4 h-4 shrink-0" />
                    </Link>
                </CardHeader>
                <CardContent className="pt-4">
                    {opportunitiesLoading ? (
                        <SectionSkeleton rows={2} />
                    ) : opportunitiesError ? (
                        <InlineSectionError message={opportunitiesError} onRetry={() => retrySection('opportunities')} />
                    ) : opportunities.length > 0 ? (
                        <>
                            <p className="mb-4 text-xs text-gray-500">
                                {dcfScopeNote(
                                    t,
                                    dcfScope ?? { probed: DCF_CANDIDATE_LIMIT, evaluated: DCF_CANDIDATE_LIMIT, failed: 0 },
                                    formatCompact(MIN_MARKET_CAP, { maximumFractionDigits: 0 }),
                                )}
                            </p>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                {visibleOpportunities.map((op) => {
                                    // La ficha DCF muestra el precio en la divisa del
                                    // listado y el valor justo SIN símbolo: el modelo
                                    // (valor justo único, /api/valuation/{ticker}/fair-value)
                                    // no garantiza la divisa del listado, así que se declara N/D
                                    // en la etiqueta en vez de suponer dólares.
                                    const priceLabel = isValidCurrencyCode(op.currency) ? t('home.opportunities.price') : t('home.opportunities.priceUnknownCurrency', { na: NA });
                                    return (
                                        <Link key={op.symbol} href={`/research/${op.symbol}?view=valuation`}>
                                            <div className="p-4 bg-gray-900/40 rounded-xl border border-gray-700/30 hover:border-purple-500/50 hover:bg-gray-800 transition-all group">
                                                <div className="flex justify-between items-start mb-2">
                                                    <div>
                                                        <h3 className="font-bold text-white group-hover:text-purple-400 transition-colors">{op.symbol}</h3>
                                                        <p className="text-xs text-gray-400">
                                                            {priceLabel}: {isValidCurrencyCode(op.currency) ? formatPrice(op.price, op.currency) : formatNumber(op.price)}
                                                        </p>
                                                    </div>
                                                    <Badge className="border-good/30 bg-good/10 text-good">
                                                        {t('home.opportunities.potential', { value: formatPercent(op.upside, { fromRatio: false, digits: 1, signDisplay: 'always' }) })}
                                                    </Badge>
                                                </div>
                                                <div className="w-full bg-gray-800 h-1.5 rounded-full mt-2 overflow-hidden">
                                                    <div
                                                        className="h-full bg-gradient-to-r from-good-strong to-good"
                                                        style={{ width: `${Math.min(op.upside, 100)}%` }}
                                                    />
                                                </div>
                                                <p className="text-xs text-gray-500 mt-2 text-right">{t('home.opportunities.fairUnknown', { na: NA, value: formatNumber(op.fairValue) })}</p>
                                                {op.fairValueLabel ? (
                                                    <p className="text-[11px] text-gray-500 mt-0.5 text-right">
                                                        {t('home.opportunities.source', { label: op.fairValueLabel })}{op.fairValueAsOf ? ` · ${formatMarketDate(op.fairValueAsOf)}` : ''}
                                                    </p>
                                                ) : null}
                                                {op.orientation ? (
                                                    <p className="text-xs text-amber-500/90 mt-1 text-right">{t('home.opportunities.orientation')}</p>
                                                ) : null}
                                            </div>
                                        </Link>
                                    );
                                })}
                            </div>
                            {/* Recortar la parrilla no puede callar lo que queda fuera. */}
                            {opportunities.length > OPPORTUNITY_TILE_LIMIT && (
                                <p className="mt-4 text-xs text-gray-500">
                                    {t('home.opportunities.topN', { limit: OPPORTUNITY_TILE_LIMIT, total: opportunities.length })}
                                </p>
                            )}
                        </>
                    ) : null}
                </CardContent>
            </Card>
            )}
        </div>
    );
}
