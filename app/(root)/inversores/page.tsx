import type { Metadata } from 'next';
import Link from 'next/link';

import BackendOffline from '@/components/system/BackendOffline';
import { getInvestors } from '@/lib/actions/investors.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatNumber } from '@/lib/format';

import { InvestorAvatar } from './_components/Avatar';
import { SyncPortfoliosButton } from './_components/SyncPortfoliosButton';
import { periodLabel, usd } from './_components/format';
import { Pagination, paginate } from './_components/Pagination';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Inversores',
    description: 'Quién invierte mejor y qué tiene en cartera, con la fuente y la fecha de cada dato.',
};

const PAGE_SIZE = 12;

type PageProps = {
    searchParams: Promise<{ pagina?: string }>;
};

export default async function InvestorsPage({ searchParams }: PageProps) {
    const { pagina } = await searchParams;
    let data: Awaited<ReturnType<typeof getInvestors>>;
    try {
        data = await getInvestors();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Inversores" retryHref="/inversores" />;
        }
        throw error;
    }

    const paged = paginate(data.investors, pagina, PAGE_SIZE);
    // Sin ningún 13F descargado, el hub ofrece la acción real en vez de una
    // lista de "sin sincronizar".
    const noneSynced = data.investors.length > 0 && data.investors.every((investor) => !investor.report_date);

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-12 overflow-x-clip py-6">
            <header className="flex flex-col gap-3">
                <h1 className="text-3xl font-semibold text-gray-100">Inversores</h1>
            </header>

            {noneSynced ? (
                <div className="flex flex-col items-center gap-4 rounded-2xl border border-gray-800 bg-surface-1 p-8 text-center">
                    <p className="text-gray-300">Aún no hay carteras descargadas en esta cuenta.</p>
                    <SyncPortfoliosButton />
                </div>
            ) : null}

            <ul className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
                {paged.items.map((investor) => (
                    <li className="min-w-0" key={investor.slug}>
                        <Link
                            className="flex h-full flex-col gap-4 rounded-2xl border border-gray-800 bg-surface-1 p-6 transition-colors hover:border-gray-700"
                            href={`/inversores/${investor.slug}`}
                        >
                            <span className="flex items-center gap-4">
                                <InvestorAvatar name={investor.name} slug={investor.slug} />
                                <span className="min-w-0">
                                    <span className="block truncate text-base font-medium text-gray-100">{investor.name}</span>
                                    <span className="block truncate text-sm text-gray-500">{investor.firm}</span>
                                </span>
                            </span>
                            {investor.report_date ? (
                                <span className="flex items-end justify-between gap-4">
                                    <span>
                                        <span className="block text-2xl font-semibold text-gray-100">{usd(investor.value_usd_thousands, investor.report_date)}</span>
                                        <span className="block text-xs text-gray-500">
                                            {investor.positions !== null
                                                ? `${formatNumber(investor.positions, { maximumFractionDigits: 0 })} posiciones`
                                                : 'N/D'}
                                        </span>
                                    </span>
                                    <span className="text-right text-xs text-gray-500">
                                        Cartera a {periodLabel(investor.report_date)}
                                        {investor.coverage === 'partial' ? (
                                            <span className="block text-amber-300">Datos parciales</span>
                                        ) : null}
                                    </span>
                                </span>
                            ) : (
                                <span className="text-sm text-gray-500">
                                    {investor.has_13f
                                        ? '13F sin sincronizar'
                                        : investor.has_public_profile
                                          ? 'Participaciones públicas · ver ficha'
                                          : 'Sin 13F · ver ficha'}
                                </span>
                            )}
                        </Link>
                    </li>
                ))}
            </ul>

            <Pagination basePath="/inversores" page={paged.page} total={paged.total} />

            <p className="text-xs text-gray-500">Fotos con licencia libre de Wikimedia Commons; autor y licencia en cada ficha. Sin foto libre, inicial.</p>
            <p className="text-xs text-gray-500">Fuente: SEC, Form 13F (EDGAR). Trimestral, con hasta 45 días de retardo; solo posiciones largas en EE. UU. Valor en dólares tal como se declara. Otras participaciones: fuente y fecha en cada ficha.</p>
        </main>
    );
}
