import type { ReactNode } from 'react';
import ResearchRateLimited from '@/components/research/ResearchRateLimited';
import { researchRateLimitWaitSeconds } from '@/lib/research/rate-limit';

/** Catch known throttling on the server BEFORE Next strips status/message. */
export async function renderWithRateLimit(load: () => Promise<ReactNode>): Promise<ReactNode> {
    try {
        return await load();
    } catch (error) {
        const waitSeconds = researchRateLimitWaitSeconds(error);
        if (waitSeconds === null) throw error;
        return <ResearchRateLimited waitSeconds={waitSeconds} />;
    }
}
