'use server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type AiFeature = 'chat' | 'thesis' | 'analysis' | 'debate';
export type AiAvailability = {
    feature: AiFeature;
    state: 'off' | 'paused' | 'degraded' | 'unverified';
    can_start: boolean;
    reason: 'disabled' | 'payment' | 'quota' | 'origin' | 'fallback' | 'not_probed';
    retry_after_seconds: number | null;
};

export async function getAiAvailability(feature: AiFeature): Promise<AiAvailability> {
    await requireAuthenticatedUser();
    return researchRequest<AiAvailability>(`/api/settings/llm/availability?feature=${encodeURIComponent(feature)}`, { cache: 'no-store' });
}
