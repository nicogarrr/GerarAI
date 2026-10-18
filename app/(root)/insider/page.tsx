import type { Metadata } from 'next';
import { Users } from 'lucide-react';
import InsiderSignalsView from '@/components/insider/InsiderSignalsView';
import BackendOffline from '@/components/system/BackendOffline';
import {
    getInsiderFilings,
    getInsiderSignals,
    type InsiderFilingsResult,
    type InsiderSignalsResult,
} from '@/lib/actions/insider.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { isAppError, isAuthError } from '@/lib/types/errors';
import { getPortfolioSummary } from '@/lib/actions/portfolio.actions';
import { getWatchlist } from '@/lib/actions/watchlist.actions';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { buildInsiderShortcuts } from '@/lib/insider/shortcuts';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Señales insider',
    description:
        'Compras insider con código P (Form 4, SEC EDGAR): clusters, compras de CEO/CFO y grandes operaciones por ticker.',
};

type PageProps = {
    searchParams: Promise<{ ticker?: string }>;
};

/** Un 4xx (ticker sin CIK, sin filings) es "no hay datos de este ticker", no
 *  el motor caído: se deja que la vista muestre su estado vacío. Excepción:
 *  401/403 no es "sin datos", es sesión caducada o acceso denegado - se
 *  propaga (isAuthError) en vez de tragarlo como ticker desconocido. */
function isUnknownTicker(error: unknown): boolean {
    return isAppError(error) && error.statusCode >= 400 && error.statusCode < 500 && !isAuthError(error);
}

export default async function InsiderPage({ searchParams }: PageProps) {
    const { ticker: rawTicker } = await searchParams;
    const ticker = rawTicker?.trim().toUpperCase() || null;
    const retryHref = ticker ? `/insider?ticker=${encodeURIComponent(ticker)}` : '/insider';
    let signals: InsiderSignalsResult | null = null;
    let filings: InsiderFilingsResult | null = null;

    if (ticker) {
        try {
            [signals, filings] = await Promise.all([getInsiderSignals(ticker), getInsiderFilings(ticker)]);
        } catch (error) {
            if (isBackendUnavailableError(error)) {
                return <BackendOffline feature="Señales Insider" retryHref={retryHref} />;
            }
            if (!isUnknownTicker(error)) throw error;
            // Ticker sin datos: la vista lo explica en vez de mostrar un error.
        }
    }

    // Atajos de solo lectura. Una lectura fallida degrada a «sin atajos», nunca
    // fabrica tickers.
    const userId = (await requireAuthenticatedUser()).id;
    const [portfolioSummary, watchlist] = await Promise.all([
        getPortfolioSummary(userId).catch(() => null),
        getWatchlist().catch(() => [] as Array<{ symbol: string }>),
    ]);
    const shortcuts = buildInsiderShortcuts(portfolioSummary?.holdings, watchlist);

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-6 overflow-x-clip">
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-sm font-semibold uppercase text-teal-300">Insider</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">Señales Insider</h1>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">
                        Compras insider con código P (Form 4, SEC EDGAR): clusters, compras de CEO/CFO y grandes operaciones.
                    </p>
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <Users className="h-4 w-4 text-teal-300" />
                    Form 4
                </div>
            </header>

            {/* La metodología y el alcance del monitor no caben en el subtítulo:
                se esconden tras un <details> en vez de anunciar aquí un monitor
                que esta pantalla no ejecuta. El resumen sí nombra el monitor,
                porque es visible sin abrir y `e2e/audit-closure.spec.ts`
                comprueba que la página siga diciendo con qué frecuencia corre. */}
            <details className="rounded-lg border border-gray-800 bg-surface-1 px-4 py-3 text-sm">
                <summary className="cursor-pointer font-semibold text-gray-300">Cómo se calculan las señales · Monitor cada 15 min sobre tu watchlist y cartera</summary>
                <div className="mt-3 space-y-2 leading-6 text-gray-400">
                    <p>
                        Se leen los Form 4 de EDGAR y sólo las transacciones con código <strong>P</strong> (compra): en
                        mercado abierto o privado, porque el XML no siempre distingue el motivo. De ahí salen tres
                        señales: <em>cluster buy</em> (varios insiders compran en pocos días), <em>C-suite buy</em> (CEO o CFO) y <em>big buy</em> (importe por encima del umbral de la estrategia).
                    </p>
                    <p>
                        El monitor automático deja el recuento de filings persistidos en el distintivo de
                        arriba; el aviso por Telegram se evalúa a mano con el botón de la tarjeta. Esta
                        pantalla es la lectura bajo demanda de un ticker concreto, no un listado del monitor.
                    </p>
                    <p>
                        Limitación conocida: EDGAR no fecha de forma fiable algunas operaciones privadas, así que un
                        <em> cluster buy</em> puede no ser una señal de mercado abierto.
                    </p>
                </div>
            </details>

            <InsiderSignalsView
                initialTicker={ticker ?? ''}
                initialResult={signals}
                initialFilings={filings}
                shortcuts={shortcuts}
            />
        </main>
    );
}
