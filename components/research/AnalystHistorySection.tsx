import { getAnalystHistory } from '@/lib/research/analyst-history';
import { AnalystHistoryView } from './AnalystHistoryView';

export async function AnalystHistorySection({ symbol }: { symbol: string }) {
    const data = await getAnalystHistory(symbol);
    return <AnalystHistoryView data={data} />;
}
