import type { DcaSignalsResponse } from '@/lib/dca/types';

export interface AttentionThesis {
    id: number;
    symbol: string;
    summary: string;
    direction: string;
    createdAt: string;
}
export interface AttentionDca {
    id: string;
    symbol: string;
    level: number;
    signalDate: string;
    forming: boolean;
    inPortfolio: boolean;
    threshold: number;
}
export interface HomeAttentionState {
    thesis: { unavailable: boolean; items: AttentionThesis[]; truncated?: boolean };
    dca: { unavailable: boolean; items: AttentionDca[] };
}

/** Current levels, not buy recommendations or claims that the thesis changed.
 * Use the server's effective preference. Never substitute a frontend default. */
export function attentionDcaItems(data: DcaSignalsResponse, now = new Date()): AttentionDca[] {
    return data.items.flatMap((item): AttentionDca[] => {
        const state = item.state;
        if ((!item.in_watchlist && !item.in_portfolio) || !state || state.stale) return [];
        const level = state.level;
        // New global policy is optional until deployed; never invent 3X/1X.
        const policy = data as DcaSignalsResponse & { alert_policy?: string; up_min_level?: number };
        const min = policy.alert_policy === 'directional'
            ? policy.up_min_level
            : item.effective_min_level;
        if (!Number.isInteger(level) || level < 1 || level > 4 || typeof min !== 'number' || !Number.isInteger(min) || min < 1 || min > 4 || level < min) return [];
        // Old backends may omit stale: fail closed on undated, future or old data.
        const stamp = Date.parse(state.signal_date);
        const age = (now.getTime() - stamp) / 86_400_000;
        if (!Number.isFinite(age) || age < 0 || age > 7) return [];
        if (state.status !== 'forming' && state.status !== 'confirmed') return [];
        return [{ id: `dca-${item.symbol}`, symbol: item.symbol, level, signalDate: state.signal_date,
            forming: state.status === 'forming', inPortfolio: item.in_portfolio, threshold: min }];
    }).sort((a, b) => b.level - a.level || a.symbol.localeCompare(b.symbol));
}
