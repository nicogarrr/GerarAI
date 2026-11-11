import type { ReactNode } from 'react';
import { randomUUID } from 'node:crypto';
import ResearchRateLimited from '@/components/research/ResearchRateLimited';
import { researchRateLimitWaitSeconds } from '@/lib/research/rate-limit';

/** Catch known throttling on the server BEFORE Next strips status/message. */
export async function renderWithRateLimit(load: () => Promise<ReactNode>): Promise<ReactNode> {
    try {
        return await load();
    } catch (error) {
        const waitSeconds = researchRateLimitWaitSeconds(error);
        if (waitSeconds === null) throw error;
        // Each failed server response is a NEW lockout, even if Retry-After is
        // unchanged. A fresh key remounts the timer and locks the button in the
        // same commit, not one interval tick later after router.refresh().
        return <ResearchRateLimited key={randomUUID()} waitSeconds={waitSeconds} />;
    }
}
