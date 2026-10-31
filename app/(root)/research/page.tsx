import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { NOT_VALUABLE, researchValuability, visibleThesisRating } from '@/lib/research/coverage-state';
import type { Metadata } from 'next';
import Link from 'next/link';
import { FileSearch } from 'lucide-react';

import { getResearchCompanySnapshots, getResearchDashboard, getResearchPortfolioPositions } from '@/lib/actions/research.actions';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { portfolioMembership } from '@/lib/research/portfolio-membership';
import { getWatchlist } from '@/lib/actions/watchlist.actions';
import BackendOffline from '@/components/system/BackendOffline';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import WorkProductButton from '@/components/work-products/WorkProductButton';
import { formatDate, formatNumber } from '@/lib/format';
import { getT } from '@/lib/i18n/server';
import type { TranslateFn } from '@/lib/i18n/translate';
import { Badge } from '@/components/ui/badge';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { Panel } from '@/components/ui/panel';
import { sectorIndustryLine } from '@/lib/labels';
import { sortCompaniesByRelevance } from '@/lib/research/relevance';
import { fetchInBatches } from '@/lib/research/snapshots';
import {
    filterResearchIndex,
    firstSearchParam,
    paginateResearchIndex,
    parseIndexPage,
    researchIndexHref,
} from '@/lib/research/index-filter';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: t('research.indexMetaTitle'),
        description: t('research.indexMetaDescription'),
    };
}

/**
 * El registro de empresas (`/api/companies`) solo trae la ficha de la empresa,
 * así que el rating y la fecha de la última tesis salen de su snapshot. Se
 * piden en llamadas batch (`/api/companies/snapshots?tickers=...`, queries
 * agregadas por IN en el backend). Quick win UX 6: el orden por relevancia
 * (tesis > cartera > watchlist > resto) exige saber qué empresas tienen
 * tesis, así que se piden TODAS en lotes del tope del endpoint (50) y se
 * reutilizan para las tarjetas de la página visible (sin segunda llamada).
 */
const SNAPSHOT_BATCH_SIZE = 50;

/** Ratings persistidos por el backend (mismo mapa que la ficha); el texto sale de research.rating.*. */
const RATING_KEYS = {
    buy: 'research.rating.buy',
    accumulate: 'research.rating.accumulate',
    overweight: 'research.rating.overweight',
    hold: 'research.rating.hold',
    underweight: 'research.rating.underweight',
    trim: 'research.rating.trim',
    sell: 'research.rating.sell',
    avoid: 'research.rating.avoid',
    watch: 'research.rating.watch',
    // Ratings del motor de tesis (thesis_service._rating): eje de valoracion,
    // no de recomendacion.
    attractive: 'research.rating.attractive',
    expensive: 'research.rating.expensive',
    incomplete_price: 'research.rating.incompletePrice',
    blocked: 'research.rating.blocked',
    insufficient_data: 'research.rating.insufficientData',
} as const;

type Dashboard = Awaited<ReturnType<typeof getResearchDashboard>>;
type Company = Dashboard['companies'][number];
type CompanySnapshot = Awaited<ReturnType<typeof getResearchCompanySnapshots>>['snapshots'][string];

type CompanyRow = {
    company: Company;
    /** null = la empresa existe en el registro pero aún no tiene research. */
    snapshot: CompanySnapshot | null;
    /** true = el snapshot no se pudo leer (backend intermitente). */
    unreadable: boolean;
};

function ratingLabel(value: string | null | undefined, t: TranslateFn): string {
    if (!value) return t('research.noRating');
    return Object.hasOwn(RATING_KEYS, value) ? t(RATING_KEYS[value as keyof typeof RATING_KEYS]) : value.replaceAll('_', ' ');
}

/** Una fila del índice: ticker, nombre, cobertura del research y última tesis. */
function CompanyCard({ row, t }: { row: CompanyRow; t: TranslateFn }) {
    const { company, snapshot, unreadable } = row;
    const health = snapshot?.research_health;
    const thesis = snapshot?.latest_thesis ?? null;
    const valuable = snapshot ? researchValuability(snapshot) !== NOT_VALUABLE : false;

    const sectorLine = sectorIndustryLine(company.sector, company.industry);

    return (
        <li>
            <Link
                className="block rounded-xl border border-gray-700/50 bg-surface-1 p-4 transition hover:border-teal-700"
                href={`/research/${encodeURIComponent(company.ticker)}`}
            >
                <div className="flex items-center gap-3">
                    {/* Mismo logo con cadena de fuentes y fallback a iniciales
                        que cartera, watchlist y cabecera de ficha. */}
                    <CompanyLogo ticker={company.ticker} name={company.name || company.ticker} className="size-10 shrink-0 rounded-lg" />
                    <div className="min-w-0">
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                            <span className="text-base font-semibold text-gray-100">{company.ticker}</span>
                            {/* line-clamp trunca visualmente: el title devuelve el texto
                                completo al usuario visual (hover), no solo al lector de pantalla. */}
                            <span className="min-w-0 line-clamp-1 text-sm text-gray-400" title={company.name}>{company.name}</span>
                        </div>
                        <p className="mt-1 line-clamp-1 text-xs text-gray-500" title={sectorLine}>
                            {sectorLine}
                        </p>
                    </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                    {unreadable ? (
                        <span className="text-xs text-warn">{t('research.unreadable')}</span>
                    ) : !snapshot ? (
                        <span className="text-xs text-gray-500">{t('research.noResearch')}</span>
                    ) : (
                        <>
                            {valuable ? (
                                <>
                                    {thesis && visibleThesisRating(thesis.rating, snapshot) ? <Badge>{ratingLabel(thesis.rating, t)}</Badge> : null}
                                    {thesis ? (
                                        <span className="text-xs text-gray-500">
                                            v{formatNumber(thesis.version)} · {formatDate(thesis.created_at)}
                                        </span>
                                    ) : null}
                                    <span
                                        className="text-xs text-gray-500"
                                        title={t('research.layersTitle')}
                                    >
                                        {t('research.layersAvailable', { score: formatNumber(health?.score) })}
                                    </span>
                                </>
                            ) : (
                                <>
                                    <span
                                        className="text-xs text-gray-500"
                                        title={t('research.layersTitle')}
                                    >
                                        {t('research.layersAvailable', { score: formatNumber(health?.score) })}
                                    </span>
                                    <span
                                        className="text-xs text-gray-500"
                                        title={t('research.notValuableTitle')}
                                    >
                                        {t('research.notValuable')}
                                    </span>
                                </>
                            )}
                        </>
                    )}
                </div>
            </Link>
        </li>
    );
}

export default async function ResearchPage({
    searchParams,
}: {
    searchParams?: Promise<{ q?: string | string[]; page?: string | string[] }>;
}) {
    const t = await getT();
    // Las lecturas de contexto del usuario (cartera, watchlist) no dependen del
    // dashboard: se lanzan a la vez en vez de esperar a que termine el
    // dashboard. Antes eran dos tramos secuenciales (dashboard, luego
    // resumen+watchlist) y el TTFB sumaba ambos.
    const userContext = (async () => {
        return Promise.all([
            getResearchPortfolioPositions().catch(() => []),
            getWatchlist().catch(() => [] as Array<{ symbol: string }>),
        ]);
    })();
    // Evita un rechazo sin manejar si el dashboard falla antes de esperarlo.
    userContext.catch(() => undefined);
    let dashboard: Dashboard;
    try {
        dashboard = await getResearchDashboard();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Research" retryHref="/research" />;
        }
        throw error;
    }
    const { companies, thesisTickers } = dashboard;

    // Contexto del usuario para el orden por relevancia. Degradación
    // honesta: una lectura fallida degrada su bucket a «resto», nunca
    // fabrica pertenencia a cartera o watchlist.
    const [portfolioPositions, watchlist] = await userContext;
    const portfolioTickers = portfolioMembership(portfolioPositions);
    const watchlistTickers = new Set(watchlist.map((item) => item.symbol.trim().toUpperCase()));

    // Quick win UX 6: tesis > cartera > watchlist > resto; empate por
    // ticker. Estable entre renders (los buckets son deterministas). La
    // pertenencia al bucket «tesis» sale de UNA query DISTINCT del backend
    // (/api/companies/thesis-tickers, misma semántica que latest_thesis del
    // snapshot), no de un snapshot por empresa: con el universo completo
    // eso eran decenas de llamadas batch en paralelo antes de paginar.
    // thesisTickers null = lectura fallida: el bucket degrada sin afirmar
    // tesis inexistentes.
    const thesisSet = new Set(thesisTickers ?? []);
    const ordered = sortCompaniesByRelevance(
        companies,
        (company) => thesisSet.has(company.ticker.trim().toUpperCase()),
        portfolioTickers,
        watchlistTickers,
    );

    const params = (await searchParams) ?? {};
    // Claves repetidas (?q=A&q=B) llegan como array: sin normalizar rompen la página.
    const query = firstSearchParam(params.q).trim();
    const requestedPage = parseIndexPage(firstSearchParam(params.page));

    // F308: filtro y paginación en servidor. Solo la página visible se
    // materializa en el HTML.
    const filtered = filterResearchIndex(ordered, query);
    const slice = paginateResearchIndex(filtered, requestedPage);

    // Snapshots SOLO de la página visible (rating/fecha de las tarjetas),
    // en lotes con fallo aislado: un lote caído marca solo sus tarjetas
    // como no leídas y conserva las demás (fetchInBatches, guard node).
    const sliceTickers = slice.rows.map((company) => company.ticker);
    const snapshotBatches = await fetchInBatches(
        sliceTickers,
        SNAPSHOT_BATCH_SIZE,
        (batch) => getResearchCompanySnapshots(batch),
    );
    const snapshotsByTicker: Record<string, CompanySnapshot> = {};
    const unreadableTickers = new Set<string>();
    snapshotBatches.forEach((part, index) => {
        const batchTickers = sliceTickers.slice(
            index * SNAPSHOT_BATCH_SIZE,
            (index + 1) * SNAPSHOT_BATCH_SIZE,
        );
        if (part === null) {
            // Lote fallido: sus tarjetas se marcan no leídas, nunca se
            // fabrican snapshots vacíos.
            batchTickers.forEach((ticker) => unreadableTickers.add(ticker));
            return;
        }
        for (const [ticker, snapshot] of Object.entries(part.snapshots)) {
            snapshotsByTicker[ticker] = snapshot;
        }
        (part.missing ?? [])
            .filter((ticker): ticker is string => Boolean(ticker))
            .forEach((ticker) => unreadableTickers.add(ticker));
    });
    const rows: CompanyRow[] = slice.rows.map((company): CompanyRow => {
        if (unreadableTickers.has(company.ticker)) {
            return { company, snapshot: null, unreadable: true };
        }
        return { company, snapshot: snapshotsByTicker[company.ticker] ?? null, unreadable: false };
    });

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
            <PageHeader
                actions={<WorkProductButton />}
                kicker={t('research.kicker')}
                title={t('research.indexTitle')}
            />

            <Panel
                title={t('research.registryTitle')}
            >
                <p className="mb-4 text-sm text-gray-400">{t('research.coverageNote')}</p>
                {ordered.length ? (
                    <>
                        <form action="/research" className="mb-4 flex flex-wrap items-center gap-2" method="get">
                            <label className="sr-only" htmlFor="research-index-q">
                                {t('research.filterLabel')}
                            </label>
                            <TickerSearchInput
                                className="min-w-0 flex-1 rounded-lg border border-gray-700 bg-surface-1 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-500 focus:border-teal-600 focus:outline-none sm:max-w-xs sm:flex-none"
                                defaultValue={query}
                                id="research-index-q"
                                name="q"
                                placeholder={t('research.filterLabel')}
                                options={ordered.map(company => ({symbol: company.ticker, name: company.name}))}
                            />
                            <button
                                className="min-h-[44px] rounded-lg border border-gray-700 px-3 py-2 text-sm text-gray-200 transition hover:border-teal-700 sm:min-h-0"
                                type="submit"
                            >
                                {t('research.filterSubmit')}
                            </button>
                            {query ? (
                                <Link
                                    className="text-sm text-teal-300 hover:text-teal-200"
                                    href="/research"
                                >
                                    {t('research.filterClear')}
                                </Link>
                            ) : null}
                        </form>
                        <p className="mb-3 text-xs text-gray-500">
                            {query
                                ? slice.total
                                    ? t('research.showingMatches', { from: formatNumber(slice.from), to: formatNumber(slice.to), total: formatNumber(slice.total), query, companies: formatNumber(ordered.length) })
                                    : t('research.zeroMatches', { query, companies: formatNumber(ordered.length) })
                                : t('research.showingAll', { from: formatNumber(slice.from), to: formatNumber(slice.to), total: formatNumber(slice.total) })}
                        </p>
                        {rows.length ? (
                            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                {rows.map((row) => (
                                    <CompanyCard key={row.company.ticker} row={row} t={t} />
                                ))}
                            </ul>
                        ) : (
                            <EmptyState
                                action={<EmptyLink href="/research">{t('research.filterClearLong')}</EmptyLink>}
                                description={t('research.noMatchDescription')}
                                icon={FileSearch}
                                title={t('research.noMatchTitle', { query })}
                            />
                        )}
                        {slice.pages > 1 ? (
                            <nav aria-label={t('research.paginationAria')} className="mt-4 flex flex-wrap items-center gap-3 text-sm">
                                {slice.page > 1 ? (
                                    <Link
                                        className="inline-flex min-h-[44px] items-center rounded-lg border border-gray-700 px-3 py-1.5 text-gray-200 transition hover:border-teal-700 sm:min-h-0"
                                        href={researchIndexHref(query, slice.page - 1)}
                                    >
                                        {t('research.previous')}
                                    </Link>
                                ) : null}
                                <span className="text-xs whitespace-nowrap text-gray-500">
                                    {t('research.pageOf', { current: formatNumber(slice.page), total: formatNumber(slice.pages) })}
                                </span>
                                {slice.page < slice.pages ? (
                                    <Link
                                        className="inline-flex min-h-[44px] items-center rounded-lg border border-gray-700 px-3 py-1.5 text-gray-200 transition hover:border-teal-700 sm:min-h-0"
                                        href={researchIndexHref(query, slice.page + 1)}
                                    >
                                        {t('research.next')}
                                    </Link>
                                ) : null}
                            </nav>
                        ) : null}
                    </>
                ) : (
                    <EmptyState
                        action={
                            <div className="flex flex-wrap justify-center gap-3">
                                <EmptyLink href="/search">{t('research.emptyActionSearch')}</EmptyLink>
                                <EmptyLink href="/watchlist">{t('research.emptyActionWatchlist')}</EmptyLink>
                            </div>
                        }
                        description={t('research.emptyDescription')}
                        icon={FileSearch}
                        title={t('research.emptyTitle')}
                    />
                )}
            </Panel>




        </main>
    );
}
