'use client';
import dynamic from 'next/dynamic';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { useT } from '@/lib/i18n/client';
function ChartLoading() {
    const t = useT();
    return <div className="h-[400px] animate-pulse rounded-xl border border-gray-800 bg-surface-1" role="status" aria-label={t('research.chart.loadingAria')} />;
}
const Chart = dynamic(() => import('./CompanyTechnicalChart'), { ssr: false, loading: ChartLoading });
export function CompanyTechnicalWorkspace({ snapshot }: { snapshot: CompanyMarketSnapshot }) {
    return <Chart snapshot={snapshot} />;
}
