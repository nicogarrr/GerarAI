'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getPreparingStatus } from '@/lib/actions/preparing-status.actions';
import { watchPreparing } from '@/lib/research/preparing-poller';

/** Poll only the pending card's state, then refresh once when data is ready. */
export default function DcaPreparingRefresh({ ticker, kind }: { ticker: string; kind: 'dca' | 'news' }) {
    const router = useRouter();
    useEffect(() => watchPreparing(`${kind}:${ticker}`, () => getPreparingStatus(ticker, kind), () => router.refresh()), [ticker, kind, router]);
    return null;
}
