'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Gauge, TrendingDown, Target } from 'lucide-react';
import type { PortfolioTearsheet } from '@/lib/actions/portfolio.actions';
import { useT, useFormat } from '@/lib/i18n/client';

type Props = {
    tearsheet: PortfolioTearsheet | null;
};

export default function PortfolioTearsheet({ tearsheet }: Props) {
    const ti = useT();
    const f = useFormat();
    const formatMetric = (value: number | null, digits = 2): string =>
        f.formatNumber(value, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    // Las métricas del tearsheet llegan como ratios (0.087 -> 8,70 %).
    const formatRatioPercent = (value: number | null, digits = 2): string =>
        f.formatPercent(value, { fromRatio: true, digits });
    const metrics = tearsheet?.metrics ?? null;

    if (!tearsheet || !metrics || metrics.n_observations < 2) {
        return (
            <Card className="bg-gray-800/50 border-gray-700">
                <CardHeader className="pb-2">
                    <CardTitle className="text-lg text-gray-100">{ti('portfolio.tearsheetExtra.title')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-sm text-gray-400">
                        {ti('portfolio.tearsheetExtra.noData')}
                    </p>
                </CardContent>
            </Card>
        );
    }

    // Sharpe null = N/D: sin signo que colorear; jamás verde por defecto.
    const sharpeColor = metrics.sharpe === null ? 'text-gray-400' : metrics.sharpe >= 0 ? 'text-green-400' : 'text-red-400';
    const items = [
        { label: 'Sharpe', value: formatMetric(metrics.sharpe), icon: Gauge, color: sharpeColor },
        { label: ti('portfolio.tearsheet.maxDrawdown'), value: formatRatioPercent(metrics.max_drawdown), icon: TrendingDown, color: 'text-orange-400' },
        { label: ti('portfolio.tearsheet.winRate'), value: formatRatioPercent(metrics.win_rate), icon: Target, color: 'text-blue-400' },
    ];

    return (
        <Card className="bg-gray-800/50 border-gray-700">
            <CardHeader className="pb-2">
                <CardTitle className="text-lg text-gray-100">{ti('portfolio.tearsheetExtra.title')}</CardTitle>
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
                    {ti('portfolio.tearsheetExtra.summaryLine', {
                        sessions: metrics.n_observations === 1 ? ti('portfolio.tearsheetExtra.sessionOne') : ti('portfolio.tearsheetExtra.sessionMany', { n: metrics.n_observations }),
                        cumReturn: formatRatioPercent(metrics.cumulative_return),
                        best: formatRatioPercent(metrics.best_day),
                        worst: formatRatioPercent(metrics.worst_day),
                    })}
                    {tearsheet.exposure ? ti('portfolio.tearsheetExtra.exposurePositions', { positions: tearsheet.exposure.n_positions === 1 ? ti('portfolio.tearsheetExtra.positionOne') : ti('portfolio.tearsheetExtra.positionMany', { n: tearsheet.exposure.n_positions }) }) : ''}
                    {tearsheet.exposure ? ti('portfolio.tearsheetExtra.exposureAsOf', { date: f.formatDate(tearsheet.exposure.snapshot_date) }) : ''}
                </p>
            </CardContent>
        </Card>
    );
}
