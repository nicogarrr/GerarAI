'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import type { PortfolioHolding } from '@/lib/actions/portfolio.actions';
import { PieChart as PieChartIcon } from 'lucide-react';
import { useT, useFormat } from '@/lib/i18n/client';
// Datos y colores desde módulos ligeros: importar valores de
// './PortfolioAllocationChart' metía recharts en la carga inicial de /portfolio.
import { COLORS } from './allocation-colors';
import { buildAllocationSlices, CASH_SLICE_SYMBOL, type AllocationSliceData as AllocationSlice } from '@/lib/portfolio-allocation';

const AllocationChartLoading = () => {
    const ti = useT();
    // h-full/w-full: el placeholder hereda el tamaño del wrapper
    // (200px bajo sm, 250px desde sm); fijo a 250 desbordaba a 360px.
    return <div className="h-full w-full animate-pulse rounded-full border border-gray-800 bg-gray-900/40" aria-label={ti('portfolio.allocation.loadingChart')} role="status" />;
};
const PortfolioAllocationChart = dynamic(() => import('./PortfolioAllocationChart'), {
    ssr: false,
    loading: AllocationChartLoading,
});

type Props = {
    holdings: PortfolioHolding[];
    /** Caja en divisa base con su signo real (negativa = margen). NO entra
     *  en el donut: se muestra como línea aparte (decisión de producto, 11 oct). */
    cash?: number | null;
    /** Moneda base para el importe del tooltip (sin ella saldría en USD). */
    baseCurrency?: string;
};

export default function PortfolioAllocation({ holdings, cash, baseCurrency }: Props) {
    const ti = useT();
    const f = useFormat();
    const hasCash = typeof cash === 'number' && cash !== 0;
    if (holdings.length === 0 && !hasCash) {
        return (
            <Card className="bg-gray-800/50 border-gray-700">
                <CardHeader className="pb-2">
                    <CardTitle className="text-gray-100 flex items-center gap-2">
                        <PieChartIcon className="h-5 w-5 text-teal-400" />
                        {ti('portfolio.allocation.emptyTitle')}
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="text-center py-8">
                        <p className="text-gray-400">{ti('portfolio.allocation.emptyHint')}</p>
                    </div>
                </CardContent>
            </Card>
        );
    }

    // Datos del donut: SOLO posiciones CON valor conocido; los pesos (sobre
    // el valor bruto de mercado) suman 100% entre ellas. Una posicion sin
    // valor (precio ausente) o con valoración suspendida NO entra mudamente
    // con 0%: queda fuera del donut y se avisa — nunca presentamos como
    // completo un reparto que no lo es (regla de veracidad).
    // El COSTE ausente (conciliación IBKR pendiente) NO excluye: el donut
    // pesa valores de mercado, no costes. Antes se usaba fxMissing, que
    // también cubre el coste, y una cartera entera con coste pendiente
    // mostraba «ninguna posición tiene valor disponible» con el valor bruto
    // a la vista (visto en prod, 2026-10-29).
    const knownHoldings = holdings.filter((holding) => !holding.valueMissing && !holding.valuationHold);
    const missingCount = holdings.length - knownHoldings.length;
    const chartData: AllocationSlice[] = buildAllocationSlices(knownHoldings);

    return (
        <div className="bg-[#111111] border border-gray-800 rounded-2xl p-6 h-full flex flex-col">
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2">
                <span className="text-gray-400 text-sm font-medium">{ti('portfolio.allocation.title')}</span>
                <span className="text-xs text-gray-500">{ti('portfolio.allocation.weightsNote')}</span>
            </div>

            {/* Contenido: Pie Chart + Leyenda */}
            <div className="flex-1 flex flex-col items-center justify-center gap-6 sm:flex-row sm:justify-between">
                {/* Pie Chart - Más grande */}
                <div className="relative h-[200px] w-[200px] flex-shrink-0 sm:h-[250px] sm:w-[250px]">
                    {chartData.length > 0 ? (
                        <PortfolioAllocationChart chartData={chartData} currency={baseCurrency} />
                    ) : (
                        <div className="flex h-full w-full items-center justify-center rounded-full border border-gray-800">
                            <span className="px-6 text-center text-sm text-gray-500">
                                {ti('portfolio.allocation.noValues')}
                            </span>
                        </div>
                    )}

                    {/* Centro del Donut (solo con donut real: sin datos el
                        mensaje N/D ya ocupa el centro y el número sobra) */}
                    {chartData.length > 0 && (
                        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                            <div className="text-center">
                                <span className="text-4xl font-bold text-white block">{knownHoldings.length}</span>
                                <span className="text-xs text-gray-500">{ti('portfolio.allocation.positionsCount')}</span>
                            </div>
                        </div>
                    )}
                </div>

                {/* Leyenda lateral - Pegada a la derecha */}
                <div id="portfolio-allocation-legend" className="max-h-[250px] w-full min-w-0 space-y-3 overflow-y-auto sm:max-h-none sm:w-auto sm:min-w-[160px] sm:max-w-[260px] sm:overflow-visible">
                    {chartData.map((item, index) => (
                        <div key={item.symbol} className="flex min-w-0 items-center justify-between gap-3">
                            <div className="flex min-w-0 items-center gap-2">
                                <div
                                    className="w-3 h-3 rounded-full"
                                    style={{ backgroundColor: COLORS[index % COLORS.length] }}
                                />
                                {item.symbol === CASH_SLICE_SYMBOL ? (
                                    <span className="text-sm text-gray-300">{ti('portfolio.allocation.cash')}</span>
                                ) : (
                                    <Link
                                        href={`/research/${item.symbol}`}
                                        className="inline-flex min-h-[44px] min-w-[44px] items-center text-sm text-gray-300 truncate hover:text-teal-300 transition-colors"
                                    >
                                        {item.symbol}
                                    </Link>
                                )}
                            </div>
                            <span className="flex-shrink-0 whitespace-nowrap text-sm text-gray-400 tabular-nums">
                                {f.formatPercent(item.percentage, { fromRatio: false, digits: 1 })}
                            </span>
                        </div>
                    ))}
                </div>
            </div>

            {missingCount > 0 && (
                <p className="mt-3 text-xs text-amber-400">
                    {ti('portfolio.allocation.incomplete', { count: `${missingCount} ${missingCount === 1 ? ti('portfolio.allocation.positionOne') : ti('portfolio.allocation.positionMany')}` })}
                </p>
            )}

            {/* Caja/margen: línea informativa aparte, con su signo real.
                Nunca entra en el donut (margen negativo daría pesos >100%). */}
            {typeof cash === 'number' && cash !== 0 && (
                <div className="mt-4 flex items-center justify-between border-t border-gray-800 pt-3 text-sm">
                    <span className="text-gray-400">{cash < 0 ? ti('portfolio.allocation.cashMargin') : ti('portfolio.allocation.cash')}</span>
                    <span className={`tabular-nums ${cash < 0 ? 'text-red-400' : 'text-gray-300'}`}>
                        {f.formatMoney(cash, baseCurrency ?? 'EUR')}
                    </span>
                </div>
            )}
        </div>
    );
}
