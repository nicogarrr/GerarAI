'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import type { DcaSignalsResponse } from '@/lib/dca/types';
import { attentionDcaItems, type HomeAttentionState } from '@/lib/overview/home-attention';
import type { components } from '@/lib/research/openapi.generated';

type WatchlistAttentionThesisOut = components['schemas']['WatchlistAttentionThesisOut'];

/** Two bounded, read-only requests. Each failure remains visible independently. */
export async function getHomeAttention(): Promise<HomeAttentionState> {
    await requireAuthenticatedUser();
    const [thesis, dca] = await Promise.allSettled([
        researchRequest<WatchlistAttentionThesisOut>('/api/watchlist/attention-thesis', { fast: true }),
        researchRequest<DcaSignalsResponse>('/api/watchlist/dca-signals', { fast: true }),
    ]);
    const thesisOk = thesis.status === 'fulfilled' && Array.isArray(thesis.value?.items);
    const dcaOk = dca.status === 'fulfilled' && Array.isArray(dca.value?.items);
    return {
        thesis: thesisOk ? { unavailable: false, ...thesis.value } : { unavailable: true, items: [] },
        dca: dcaOk ? { unavailable: false, items: attentionDcaItems(dca.value) } : { unavailable: true, items: [] },
    };
}
