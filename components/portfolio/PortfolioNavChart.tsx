'use client';

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { useT, useFormat } from '@/lib/i18n/client';
import { navYDomain } from '@/lib/portfolio/nav-domain';

export type NavPoint = {
    date: string;
    value: number;
};

type Props = {
    data: NavPoint[];
    positive: boolean;
    /** Divisa base de la cartera (la misma que el resumen). */
    currency?: string;
};

/** Gráfico de área del NAV (carga diferida: recharts no va al bundle inicial). */
export default function PortfolioNavChart({ data, positive, currency = 'USD' }: Props) {
    const ti = useT();
    const f = useFormat();
    const color = positive ? '#14b8a6' : '#ef4444';
    return (
        <ResponsiveContainer
            width="100%"
            height="100%"
            // Recharts 3.3: initialDimension por defecto es {-1,-1} y el primer
            // render (antes de que el ResizeObserver mida) dispara el warning
            // dev "width(-1) and height(-1)". Damos un tamano inicial positivo
            // (altura fija del wrapper h-[200px]; ancho estimado del caso
            // movil, no una medicion real) y el ResizeObserver lo corrige al
            // montar.
            initialDimension={{ width: 320, height: 200 }}
        >
            <AreaChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
                <defs>
                    <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={color} stopOpacity={0} />
                    </linearGradient>
                </defs>
                <XAxis
                    dataKey="date"
                    axisLine={false}
                    tickLine={false}
                    // #a1a1aa = gray-500 de la paleta del repo (globals.css):
                    // 7,4:1 sobre el fondo real del grafico (#111111, medido en prod).
                    tick={{ fill: '#a1a1aa', fontSize: 11 }}
                    interval="preserveStartEnd"
                />
                <YAxis hide domain={navYDomain(data.map((point) => point.value))} />
                <Tooltip
                    contentStyle={{
                        backgroundColor: '#1f2937',
                        border: '1px solid #374151',
                        borderRadius: '8px',
                    }}
                    labelStyle={{ color: '#9ca3af' }}
                    formatter={(value) => [f.formatMoney(Number(value), currency), ti('portfolio.navChart.valueLabel')]}
                />
                <Area
                    type="monotone"
                    dataKey="value"
                    stroke={color}
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorValue)"
                />
            </AreaChart>
        </ResponsiveContainer>
    );
}
