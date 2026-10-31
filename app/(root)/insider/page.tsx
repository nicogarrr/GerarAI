import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import InsiderFeed from '@/components/insider/InsiderFeed';
import InsiderOperationsView from '@/components/insider/InsiderOperationsView';
import InsiderSignalsView from '@/components/insider/InsiderSignalsView';
import BackendOffline from '@/components/system/BackendOffline';
import {
    getInsiderFeed,
    getInsiderFilings,
    getInsiderOperations,
    getInsiderSignals,
    type InsiderFeedResult,
    type InsiderFilingsResult,
    type InsiderOperationsResult,
    type InsiderSignalsResult,
} from '@/lib/actions/insider.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { isAppError, isAuthError } from '@/lib/types/errors';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: t('insider.meta.title'),
        description: t('insider.meta.description'),
    };
}

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
    const t = await getT();
    const { ticker: rawTicker, lado, dias } = await searchParams;
    const side = lado === 'buy' || lado === 'sell' ? lado : 'all';
    const days = [30, 365].includes(Number(dias)) ? Number(dias) : 90;
    const ticker = rawTicker?.trim().toUpperCase() || null;
    const params = new URLSearchParams();
    if (ticker) params.set('ticker', ticker);
    if (lado) params.set('lado', lado);
    if (dias) params.set('dias', dias);
    const queryString = params.toString();
    const retryHref = queryString ? `/insider?${queryString}` : '/insider';
    let signals: InsiderSignalsResult | null = null;
    let filings: InsiderFilingsResult | null = null;
    let feed: InsiderFeedResult | null = null;
    let operations: InsiderOperationsResult | null = null;

    if (ticker) {
        try {
            [signals, filings] = await Promise.all([getInsiderSignals(ticker), getInsiderFilings(ticker)]);
        } catch (error) {
            if (isBackendUnavailableError(error)) {
                return <BackendOffline feature={t('insider.meta.backendFeature')} retryHref={retryHref} />;
            }
            if (!isUnknownTicker(error)) throw error;
            // Ticker sin datos: la vista lo explica en vez de mostrar un error.
        }
    }

    if (!ticker) {
        // Feed y agregado por empresa son lecturas independientes: que una
        // falle no puede tumbar la otra (estado honesto por seccion).
        let feedError: unknown = null;
        let opsError: unknown = null;
        [feed, operations] = await Promise.all([
            getInsiderFeed(side, days).catch((error) => {
                if (isAuthError(error)) throw error;
                feedError = error;
                return null;
            }),
            getInsiderOperations(365).catch((error) => {
                if (isAuthError(error)) throw error;
                opsError = error;
                return null;
            }),
        ]);
        if (isBackendUnavailableError(feedError) && isBackendUnavailableError(opsError)) {
            return <BackendOffline feature={t('insider.meta.backendFeature')} retryHref={retryHref} />;
        }
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-6 overflow-x-clip">
            {ticker ? (
                <Link
                    className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-200"
                    href={`/research/${encodeURIComponent(ticker)}`}
                >
                    <ArrowLeft aria-hidden="true" className="h-4 w-4" />
                    {t('insider.backToTicker', { ticker })}
                </Link>
            ) : null}
            <header className="border-b border-gray-800 pb-4">
                <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">{t('insider.header.title')}</h1>
            </header>

            <InsiderSignalsView
                initialTicker={ticker ?? ''}
                initialResult={signals}
                initialFilings={filings}
            />
            {!ticker ? (
                <>
                    <InsiderOperationsView days={365} result={operations} />
                    <InsiderFeed days={days} feed={feed} side={side} />
                </>
            ) : null}
        </main>
    );
}
