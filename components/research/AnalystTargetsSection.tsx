import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';
import { AnalystTargetsView } from './AnalystTargetsView';
type AnalystTargets = components['schemas']['AnalystTargets'];
export async function AnalystTargetsSection({ symbol, currency }: { symbol: string; currency?: string | null }) {
    let data: AnalystTargets | null = null;
    try {
        data = await researchRequest<AnalystTargets>(`/api/companies/${encodeURIComponent(symbol)}/analyst-targets`, { timeoutMs: 14000 });
    } catch { data = null; }
    return <AnalystTargetsView data={data} currency={currency} />;
}
