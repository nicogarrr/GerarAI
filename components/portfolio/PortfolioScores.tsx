'use client';

import Link from 'next/link';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Shield, TrendingUp, CircleDollarSign, Coins, Percent } from 'lucide-react';
import { portfolioScoreDisplay } from '@/lib/portfolio-score-display';
import { useT, useFormat } from '@/lib/i18n/client';

interface PortfolioScoresProps {
    scores: {
        quality: number | null;
        growth: number | null;
        value: number | null;
        dividend: number | null;
        cagr3y: number | null;
    };
}

export default function PortfolioScores({ scores }: PortfolioScoresProps) {
    const ti = useT();
    const f = useFormat();
    const scoreItems = [
        { label: ti('portfolio.scores.quality'), value: scores.quality, icon: Shield, color: 'text-purple-400' },
        { label: ti('portfolio.scores.growth'), value: scores.growth, icon: TrendingUp, color: 'text-blue-400' },
        { label: ti('portfolio.scores.value'), value: scores.value, icon: CircleDollarSign, color: 'text-green-400' },
        { label: ti('portfolio.scores.dividend'), value: scores.dividend, icon: Coins, color: 'text-yellow-400' },
        { label: ti('portfolio.scoresExtra.cumulativeReturn'), value: scores.cagr3y, icon: Percent, color: 'text-teal-400', isPercent: true },
    ];
    const missing = scoreItems.filter((item) => item.value == null).map((item) => item.label);

    return (
        <Card className="bg-gray-800/50 border-gray-700">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-lg text-gray-100">{ti('portfolio.scoresExtra.title')}</CardTitle>
                <Link href="/metodologia" className="inline-flex min-h-[44px] items-center text-sm text-purple-300 underline-offset-2 hover:text-purple-200 hover:underline">
                    {ti('portfolio.scoresExtra.methodologyLink')}
                </Link>
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
                    {scoreItems.map((item) => {
                        const display = portfolioScoreDisplay(item.value, item.isPercent);
                        return (
                            <div key={item.label} className="text-center p-3 bg-gray-900/50 rounded-lg">
                                <item.icon className={`h-6 w-6 mx-auto mb-2 ${item.color}`} />
                                {display.kind === 'no-data' ? (
                                    // F255: la columna sin datos también nombra su factor;
                                    // si no, cinco iconos iguales no dicen qué falta.
                                    <>
                                        <div
                                            className="text-2xl font-bold text-gray-500"
                                            title={ti('portfolio.scoresExtra.noDataTitle')}
                                        >
                                            &mdash;
                                        </div>
                                        <div className="text-xs text-gray-400">{item.label}</div>
                                        <div className="text-[10px] uppercase tracking-wide text-gray-500">
                                            {ti('portfolio.scoresExtra.noData')}
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        <div className="text-2xl font-bold text-gray-100">
                                            {display.isPercent
                                                ? f.formatPercent(display.value, { fromRatio: false, digits: 2 })
                                                : f.formatNumber(display.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                        </div>
                                        <div className="text-xs text-gray-400">{item.label}</div>
                                    </>
                                )}
                            </div>
                        );
                    })}
                </div>
                <p className="mt-3 text-xs text-gray-400">
                    {ti('portfolio.scoresExtra.explanation')}
                </p>
                {missing.length > 0 && (
                    <p className="mt-3 text-xs text-gray-500">
                        {ti('portfolio.scoresExtra.missingFor', { labels: missing.join(', ') })}
                    </p>
                )}
            </CardContent>
        </Card>
    );
}
