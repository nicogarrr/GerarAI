'use server';

import { getAnalystTargets } from '@/lib/research/analyst-targets';
import { getAnalystHistory } from '@/lib/research/analyst-history';

// Called only when the responsive panel mounts. Existing authenticated clients
// keep the same sources, budgets and unavailable/null semantics.
export async function readAnalystTargets(symbol: string) {
    return getAnalystTargets(symbol);
}
export async function readAnalystHistory(symbol: string) {
    return getAnalystHistory(symbol);
}
