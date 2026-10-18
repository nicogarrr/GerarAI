import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft, Users } from 'lucide-react';
import InsiderFeed from '@/components/insider/InsiderFeed';
import InsiderSignalsView from '@/components/insider/InsiderSignalsView';
import BackendOffline from '@/components/system/BackendOffline';
import {
    getInsiderFeed,
    getInsiderFilings,
    getInsiderSignals,
    type InsiderFeedResult,
    type InsiderFilingsResult,
    type InsiderSignalsResult,
} from '@/lib/actions/insider.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { isAppError, isAuthError } from '@/lib/types/errors';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Señales insider',
    description:
        'Compras insider con código P (Form 4, SEC EDGAR): clusters, compras de CEO/CFO y grandes operaciones por ticker.',
};

type PageProps = {
    searchParams: Promise<{ ticker?: string; lado?: string; dias?: string }>;
};

/** Un 4xx (ticker sin CIK, sin filings) es "no hay datos de este ticker", no
 *  el motor caído: se deja que la vista muestre su estado vacío. Excepción:
 *  401/403 no es "sin datos", es sesión caducada o acceso denegado - se
 *  propaga (isAuthError) en vez de tragarlo como ticker desconocido. */
function isUnknownTicker(error: unknown): boolean {
    return isAppError(error) && error.statusCode >= 400 && error.statusCode < 500 && !isAuthError(error);
}

export default async function InsiderPage({ searchParams }: PageProps) {
    const { ticker: rawTicker, lado, dias } = await searchParams;
    const side = lado === 'buy' || lado === 'sell' ? lado : 'all';
    const days = [30, 365].includes(Number(dias)) ? Number(dias) : 90;
    const ticker = rawTicker?.trim().toUpperCase() || null;
    const retryHref = ticker ? `/insider?ticker=${encodeURIComponent(ticker)}` : '/insider';
    let signals: InsiderSignalsResult | null = null;
    let filings: InsiderFilingsResult | null = null;
    let feed: InsiderFeedResult | null = null;

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

    if (!ticker) {
        feed = await getInsiderFeed(side, days).catch((error) => {
            if (isAuthError(error)) throw error;
            return null;
        });
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-6 overflow-x-clip">
            {ticker ? (
                <Link
                    className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-200"
                    href={`/research/${encodeURIComponent(ticker)}`}
                >
                    <ArrowLeft aria-hidden="true" className="h-4 w-4" />
                    Volver a {ticker}
                </Link>
            ) : null}
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-sm font-semibold uppercase text-teal-300">Insider</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">Señales Insider</h1>
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <Users className="h-4 w-4 text-teal-300" />
                    Form 4
                </div>
            </header>

            <details className="rounded-lg border border-gray-800 bg-surface-1 px-4 py-3 text-sm">
                <summary className="cursor-pointer font-semibold text-gray-300">Metodología · Monitor cada 15 min sobre tu watchlist y cartera</summary>
                <ul className="mt-3 list-disc space-y-1 pl-5 leading-6 text-gray-400">
                    <li>Form 4 de EDGAR; compra = código <strong>P</strong> (mercado abierto o privado), venta = código <strong>S</strong>.</li>
                    <li><em>Cluster buy</em>: 3 o más insiders compran en 30 días. <em>C-suite buy</em> (CEO o CFO). <em>Big buy</em>: más de $1.000.000.</li>
                    <li>El monitor automático guarda los filings; esta pantalla lee lo guardado.</li>
                </ul>
            </details>

            <InsiderSignalsView
                initialTicker={ticker ?? ''}
                initialResult={signals}
                initialFilings={filings}
            />
            {!ticker ? <InsiderFeed days={days} feed={feed} side={side} /> : null}
        </main>
    );
}
