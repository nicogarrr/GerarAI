import { expect, it } from 'vitest';
import { AppError } from '@/lib/types/errors';
import { researchRateLimitWaitSeconds, researchRetryAfterSeconds } from '@/lib/research/rate-limit';

it.each([null, '', ' ', '-10', '0', 'NaN', 'nonsense', 'Infinity'])('uses sliding-window-safe default for Retry-After %s', value => {
    expect(researchRetryAfterSeconds(value, 0)).toBe(60);
});
it('honors longer Retry-After seconds and dates and rounds up', () => {
    expect(researchRetryAfterSeconds('120.1', 0)).toBe(121);
    expect(researchRetryAfterSeconds('Thu, 01 Jan 1970 00:02:00 GMT', 0)).toBe(120);
    expect(researchRetryAfterSeconds('1', 0)).toBe(60);
    expect(researchRetryAfterSeconds('Thu, 01 Jan 1970 00:00:00 GMT', 1000)).toBe(60);
});
it.each([undefined, null, {}, { retryAfterSeconds: -1 }, { retryAfterSeconds: Infinity }, { retryAfterSeconds: '120' }])('handles missing or invalid error metadata %j', cause => {
    expect(researchRateLimitWaitSeconds(new AppError('429', 'RESEARCH_API_ERROR', 429, cause))).toBe(60);
});
it('reads the final response metadata and rejects unrelated errors', () => {
    expect(researchRateLimitWaitSeconds(new AppError('throttled', 'RESEARCH_API_ERROR', 429, { retryAfterSeconds: 120.2 }))).toBe(121);
    expect(researchRateLimitWaitSeconds(new Error('429 Rate limit exceeded'))).toBeNull();
    expect(researchRateLimitWaitSeconds(null)).toBeNull();
});
