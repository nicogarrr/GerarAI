import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft, Building2 } from 'lucide-react';
import CorporateActionsView from '@/components/corporate-actions/CorporateActionsView';
import BackendOffline from '@/components/system/BackendOffline';
import { getCorporateActions, getCorporateActionsSyncStatus, type CorporateActionRecord } from '@/lib/actions/corporate-actions.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatNumber } from '@/lib/format';
import { corporateActionsEmptyMessage } from '@/lib/research/corporate-actions-empty';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Acciones corporativas',
    description:
        'Dividendos, splits, spin-offs y fusiones: revisa los eventos pendientes y aplícalos a tu cartera.',
};

type PageProps = { searchParams: Promise<{ ticker?: string }> };

export default async function CorporateActionsPage({ searchParams }: PageProps) {
    const { ticker: rawTicker } = await searchParams;
    const ticker = rawTicker?.trim().toUpperCase() || null;
    let actions: CorporateActionRecord[];
    try {
        actions = await getCorporateActions();
    } catch (error) {
        // Antes un fallo de red se traducía en `[]` y la cuenta de eventos
        // llegaba a la pantalla: el usuario leía "0 eventos" con el motor
        // apagado, indistinguible de "no tienes eventos pendientes".
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Acciones corporativas" retryHref="/corporate-actions" />;
        }
        throw error;
    }

    const visibleCount = ticker
        ? actions.filter((action) => String(action.ticker ?? '').toUpperCase() === ticker).length
        : actions.length;

    const syncStatus = visibleCount === 0
        ? await getCorporateActionsSyncStatus().catch(() => null)
        : null;

    const emptyMessage = visibleCount === 0
        ? (ticker
            ? `Sin eventos pendientes de ${ticker}.`
            : corporateActionsEmptyMessage(syncStatus))
        : undefined;

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
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
                    <p className="text-sm font-semibold uppercase text-teal-300">Eventos corporativos</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">Acciones corporativas</h1>
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <Building2 className="h-4 w-4 text-teal-300" />
                    {formatNumber(visibleCount, { maximumFractionDigits: 0 })} eventos
                </div>
            </header>

            <CorporateActionsView emptyMessage={emptyMessage} initialActions={actions} ticker={ticker} />
        </main>
    );
}
