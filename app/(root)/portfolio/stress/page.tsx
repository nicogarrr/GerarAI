import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import type { Metadata } from 'next';
import Link from 'next/link';
import HistoricalStressView from '@/components/historical-stress/HistoricalStressView';
import BackendOffline from '@/components/system/BackendOffline';
import { getHistoricalStress } from '@/lib/actions/historical-stress.actions';
import type { HistoricalStressReport } from '@/types/historical-stress';
import { isBackendUnavailableError } from '@/lib/backend-offline';

export const dynamic = 'force-dynamic';
export const metadata: Metadata = { title: 'Estrés histórico', description: 'Caídas y recuperación en 2008, 2020 y 2022.' };

export default async function HistoricalStressPage({ searchParams }: { searchParams: Promise<{ ticker?: string }> }) {
    const { ticker: raw } = await searchParams;
    const ticker = raw?.trim().toUpperCase();
    if (ticker && !/^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/.test(ticker)) {
        return <main id="content" className="p-6"><p>Ticker no válido.</p><Link href="/portfolio/stress">Volver</Link></main>;
    }
    let report: HistoricalStressReport;
    try {
        report = await getHistoricalStress(ticker);
    } catch (error) {
        if (isBackendUnavailableError(error)) return <BackendOffline feature="Estrés histórico" retryHref={ticker ? `/portfolio/stress?ticker=${encodeURIComponent(ticker)}` : '/portfolio/stress'} />;
        throw error;
    }
        return <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
            <header className="border-b border-gray-800 pb-5">
                <Link className="inline-flex min-h-11 items-center text-sm text-teal-300" href="/portfolio/intelligence">Inteligencia de cartera</Link>
                <h1 className="mt-3 text-3xl font-bold text-gray-100">Estrés histórico</h1>
                <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
                    <label className="text-sm text-gray-400">Compañía<TickerSearchInput className="mt-1 block min-h-11 w-40 rounded border border-gray-700 bg-surface-1 px-3 py-2 text-gray-100" name="ticker" maxLength={20} defaultValue={ticker} placeholder="AAPL" /></label>
                    <button className="min-h-11 min-w-11 rounded bg-teal-800 px-4 py-2 text-sm text-white" type="submit">Analizar</button>
                    <Link className="inline-flex min-h-11 items-center px-2 py-2 text-sm text-teal-300" href="/portfolio/stress">Mi cartera</Link>
                </form>
            </header>
            <HistoricalStressView report={report} />
        </main>;
}
