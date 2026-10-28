'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Gauge, TrendingDown, Target } from 'lucide-react';
import type { PortfolioTearsheet } from '@/lib/actions/portfolio.actions';
import { formatDate, formatNumber, formatPercent, formatCountEs } from '@/lib/format';
import { t } from '@/lib/i18n/t';

type Props = {
    tearsheet: PortfolioTearsheet | null;
};

function formatMetric(value: number | null, digits = 2): string {
    return formatNumber(value, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Las métricas del tearsheet llegan como ratios (0.087 -> 8,70 %). */
function formatRatioPercent(value: number | null, digits = 2): string {
    return formatPercent(value, { fromRatio: true, digits });
}

export default function PortfolioTearsheet({ tearsheet }: Props) {
    const metrics = tearsheet?.metrics ?? null;

    if (!tearsheet || !metrics || metrics.n_observations < 2) {
        return (
            <Card className="bg-gray-800/50 border-gray-700">
                <CardHeader className="pb-2">
                    <CardTitle className="text-lg text-gray-100">Estadísticas de rentabilidad</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-sm text-gray-400">
                        No hay retornos suficientes para calcular Sharpe, caída máxima o porcentaje de días positivos.
                    </p>
                </CardContent>
            </Card>
        );
    }

    // Sharpe null = N/D: sin signo que colorear; jamás verde por defecto.
    const sharpeColor = metrics.sharpe === null ? 'text-gray-400' : metrics.sharpe >= 0 ? 'text-green-400' : 'text-red-400';
    const items = [
        { label: 'Sharpe', value: formatMetric(metrics.sharpe), icon: Gauge, color: sharpeColor },
        { label: t('portfolio.tearsheet.maxDrawdown'), value: formatRatioPercent(metrics.max_drawdown), icon: TrendingDown, color: 'text-orange-400' },
        { label: t('portfolio.tearsheet.winRate'), value: formatRatioPercent(metrics.win_rate), icon: Target, color: 'text-blue-400' },
    ];

    return (
        <Card className="bg-gray-800/50 border-gray-700">
            <CardHeader className="pb-2">
                <CardTitle className="text-lg text-gray-100">Estadísticas de rentabilidad</CardTitle>
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-3 gap-4">
                    {items.map((item) => (
                        <div key={item.label} className="text-center p-3 bg-gray-900/50 rounded-lg">
                            <item.icon className={`h-6 w-6 mx-auto mb-2 ${item.color}`} />
                            <div className="text-2xl font-bold text-gray-100">{item.value}</div>
                            <div className="text-xs text-gray-400">{item.label}</div>
                        </div>
                    ))}
                </div>
                <p className="mt-3 text-xs text-gray-500">
                    {formatCountEs(metrics.n_observations, 'sesión', 'sesiones')} · Ret. acumulado{' '}
                    {formatRatioPercent(metrics.cumulative_return)} · Mejor día {formatRatioPercent(metrics.best_day)} · Peor día{' '}
                    {formatRatioPercent(metrics.worst_day)}
                    {tearsheet.exposure ? ` · ${formatCountEs(tearsheet.exposure.n_positions, 'posición', 'posiciones')}` : ''}
                    {tearsheet.exposure ? ` · datos hasta el ${formatDate(tearsheet.exposure.snapshot_date)}` : ''}
                </p>
            </CardContent>
        </Card>
    );
}
