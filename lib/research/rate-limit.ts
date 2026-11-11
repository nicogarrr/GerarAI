import { AppError } from '@/lib/types/errors';

// Rejected requests also count in the backend's 60s sliding window. Without
// Retry-After, a short/immediate retry would keep extending the lockout.
export const RATE_LIMIT_DEFAULT_WAIT_SECONDS = 60;

export function researchRetryAfterSeconds(header: string | null, now = Date.now()): number {
    if (!header?.trim()) return RATE_LIMIT_DEFAULT_WAIT_SECONDS;
    const numeric = Number(header);
    const seconds = Number.isFinite(numeric) ? numeric : (Date.parse(header) - now) / 1000;
    return Number.isFinite(seconds) && seconds > 0
        ? Math.max(RATE_LIMIT_DEFAULT_WAIT_SECONDS, Math.ceil(seconds))
        : RATE_LIMIT_DEFAULT_WAIT_SECONDS;
}

export function researchRateLimitWaitSeconds(error: unknown): number | null {
    if (!(error instanceof AppError) || error.statusCode !== 429) return null;
    const seconds = (error.cause as { retryAfterSeconds?: unknown } | null)?.retryAfterSeconds;
    return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0
        ? Math.max(RATE_LIMIT_DEFAULT_WAIT_SECONDS, Math.ceil(seconds))
        : RATE_LIMIT_DEFAULT_WAIT_SECONDS;
}
