'use client';

import { useEffect, useState } from 'react';
import { readAnalystHistory, readAnalystTargets } from '@/lib/actions/analyst-panels.actions';
import { AnalystTargetsView } from './AnalystTargetsView';
import { AnalystHistorySkeleton, AnalystHistoryView } from './AnalystHistoryView';
import type { AnalystTargets } from '@/lib/research/analyst-targets';
import { useT } from '@/lib/i18n/client';

function usePanel<T>(symbol: string, read: (symbol: string) => Promise<T | null>, initial?: Promise<T | null>) {
    const [loaded, setLoaded] = useState<{ symbol: string; value: T | null } | null>(null);
    useEffect(() => {
        let active = true;
        void (initial ?? read(symbol)).catch(() => null).then((value) => {
            if (active) setLoaded({ symbol, value });
        });
        return () => { active = false; };
    }, [symbol, read, initial]);
    return loaded?.symbol === symbol ? loaded : null;
}

export function DeferredAnalystTargets({ symbol, currency, initial }: { symbol: string; currency?: string | null; initial?: Promise<AnalystTargets | null> }) {
    const data = usePanel(symbol, readAnalystTargets, initial);
    const t = useT();
    return data ? <AnalystTargetsView data={data.value} currency={currency} />
        : <p role="status" className="p-3 text-xs text-gray-400">{t('common.states.loading')}</p>;
}

export function DeferredAnalystHistory({ symbol }: { symbol: string }) {
    const data = usePanel(symbol, readAnalystHistory);
    return data ? <AnalystHistoryView data={data.value} /> : <AnalystHistorySkeleton />;
}
