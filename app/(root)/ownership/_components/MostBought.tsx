import Link from 'next/link';

import BackendOffline from '@/components/system/BackendOffline';
import { getMostBought } from '@/lib/actions/investors.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatMarketCapUsd, formatNumber, NA } from '@/lib/format';

import { periodLabel } from '../../inversores/_components/format';
import { newLabel } from '../../inversores/_components/labels';
import { Pagination, paginate } from '../../inversores/_components/Pagination';
import { SyncPortfoliosButton } from '../../inversores/_components/SyncPortfoliosButton';

const PAGE_SIZE = 10;

/** Vista "Más compradas" de Movimientos 13F: ranking de emisores que más
 *  gestores añadieron en su último 13F frente al trimestre anterior.
 *  Antes /inversores/mas-compradas (fusionada aquí, decisión de Nico 2026-10-20). */
export async function MostBought({ pagina }: { pagina?: string }) {
    let data: Awaited<ReturnType<typeof getMostBought>>;
    try {
        data = await getMostBought();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline as="section" feature="Más compradas" retryHref="/ownership?vista=mas-compradas" />;
        }
        throw error;
    }
    const paged = paginate(data.items, pagina, PAGE_SIZE);
    const period = data.report_dates.map((date) => periodLabel(date)).join(', ');

    return (
        <>
            <p className="text-base text-gray-400">Lo que más inversores añadieron a su cartera en el último trimestre.</p>

            {data.status === 'sin_datos' || data.items.length === 0 ? (
                <div className="flex flex-col items-center gap-4 rounded-2xl border border-gray-800 bg-surface-1 p-8 text-center">
                    <p className="text-base text-gray-500">Sin datos todavía: faltan dos trimestres de 13F sincronizados.</p>
                    <SyncPortfoliosButton />
                </div>
            ) : (
                <ul className="flex flex-col gap-4">
                    {paged.items.map((item) => (
                        <li className="flex flex-col gap-3 rounded-2xl border border-gray-800 bg-surface-1 p-6" key={item.cusip}>
                            <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:gap-4">
                                <div className="min-w-0">
                                    <p className="break-words text-base font-medium text-gray-100">{item.name_of_issuer}</p>
                                    <p className="text-xs text-gray-500">CUSIP {item.cusip}</p>
                                </div>
                                <div className="min-w-0 sm:text-right">
                                    <p className="text-2xl font-semibold text-gray-100">
                                        {formatNumber(item.buyers_count, { maximumFractionDigits: 0 })} compran
                                    </p>
                                    <p className="text-xs text-gray-500">
                                        {item.new_count > 0 ? `${newLabel(item.new_count)} · ` : ''}
                                        {item.sellers_count > 0 ? `${formatNumber(item.sellers_count, { maximumFractionDigits: 0 })} reducen · ` : ''}
                                        {item.value_usd === null ? NA : formatMarketCapUsd(item.value_usd)}
                                    </p>
                                </div>
                            </div>
                            <p className="text-sm text-gray-400">
                                {item.buyers.map((buyer, index) => (
                                    <span key={buyer.slug}>
                                        {index > 0 ? ', ' : ''}
                                        <Link className="hover:underline" href={`/inversores/${buyer.slug}`}>
                                            {buyer.name}
                                        </Link>
                                    </span>
                                ))}
                            </p>
                        </li>
                    ))}
                </ul>
            )}

            <Pagination basePath="/ownership" page={paged.page} total={paged.total} params={{ vista: 'mas-compradas' }} />

            <p className="text-xs text-gray-500">
                Fuente: SEC, Form 13F (EDGAR){period ? `, informes a ${period}` : ''}. Trimestral, con hasta 45 días de retardo.
                Compara cada inversor con su trimestre anterior ({data.managers_compared} comparados
                {data.managers_without_history > 0 ? `, ${data.managers_without_history} sin dos trimestres todavía` : ''}
                {data.managers_partial ? `, ${data.managers_partial} con datos parciales` : ''}). Solo
                acciones largas en EE. UU.; las opciones no cuentan. El 13F no trae ticker, se muestra el emisor y su CUSIP.
                Valor = posición actual de quienes compran, en dólares.
            </p>
        </>
    );
}
