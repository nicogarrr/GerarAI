'use client';

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

import { useT, useFormat } from '@/lib/i18n/client';
import { AllocationTooltip } from './AllocationTooltip';
import { COLORS } from './allocation-colors';
import { buildAllocationSlices, CASH_SLICE_SYMBOL, type AllocationSliceData } from '@/lib/portfolio-allocation';

export type AllocationSlice = AllocationSliceData;
export { buildAllocationSlices, CASH_SLICE_SYMBOL };

/** Donut de distribución: se carga solo en cliente (dynamic ssr:false desde el panel) */
export default function PortfolioAllocationChart({ chartData, currency }: { chartData: AllocationSlice[]; currency?: string }) {
    const ti = useT();
    const f = useFormat();
    return (
        <ResponsiveContainer
            width="100%"
            height="100%"
            // Recharts 3.3: initialDimension por defecto es {-1,-1} y el primer
            // render dispara el warning dev "width(-1) and height(-1)". Damos
            // un tamano inicial positivo (la caja fija del wrapper,
            // h/w-[200px] y 250 en sm) y el ResizeObserver lo corrige al
            // montar.
            initialDimension={{ width: 200, height: 200 }}
        >
            <PieChart>
                <Pie
                    data={chartData}
                    cx="50%"
                    cy="50%"
                    // Radios relativos al contenedor: con valores fijos
                    // (70/105 -> diametro 210) el wrapper de 200px bajo sm
                    // recortaba 5px por lado (F337).
                    innerRadius="56%"
                    outerRadius="84%"
                    paddingAngle={2}
                    dataKey="value"
                    nameKey="symbol"
                    animationBegin={0}
                    animationDuration={800}
                >
                    {chartData.map((entry, index) => (
                        <Cell
                            key={`cell-${entry.symbol}`}
                            fill={COLORS[index % COLORS.length]}
                            stroke="rgba(0,0,0,0)"
                            strokeWidth={0}
                        />
                    ))}
                </Pie>
                <Tooltip content={<AllocationTooltip currency={currency} f={f} labels={{ value: ti('portfolio.allocationTooltip.value'), weight: ti('portfolio.allocationTooltip.weight'), pnl: ti('portfolio.allocationTooltip.pnl') }} />} />
            </PieChart>
        </ResponsiveContainer>
    );
}

export { COLORS };
