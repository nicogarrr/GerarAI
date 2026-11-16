import { z } from 'zod';

const status = z.enum(['ok', 'empty', 'partial', 'error']);
const dataStatus = z.enum(['ok', 'missing', 'stale', 'disputed', 'unverified', 'invalid', 'not_applicable']);
const errors = z.enum(['timeout', 'unauthenticated', 'forbidden', 'rate_limited', 'unavailable', 'invalid_response']);
const strings = z.array(z.string());
const datum = z.object({
    status: dataStatus,
    value: z.union([z.number(), z.string(), z.boolean(), z.null()]).optional(),
});
const block = z.object({
    status,
    error: z.object({ kind: errors }).nullish(),
});
const pick = z.object({
    instrumentId: z.string(),
    asOf: z.string(),
    listing: z.object({
        ticker: z.string(), name: z.string().nullish(),
        status: z.enum(['active', 'delisted', 'unknown']),
        instrumentStatus: z.enum(['active', 'cancelled', 'unknown']),
        tradingStatus: z.enum(['trading', 'suspended', 'unknown']),
    }),
    quality: z.object({ score: datum, passed: z.boolean().nullish(), reasonCodes: strings }),
    valuation: z.object({ status: dataStatus, price: datum, marginOfSafety: datum }),
    dca: z.object({ status: dataStatus, level: datum, periodState: z.enum(['confirmed', 'forming']).nullish() }),
    tracking: z.object({ held: z.boolean().nullish(), watched: z.boolean().nullish() }),
    eligibility: z.object({ state: z.enum(['investigate', 'quality_waiting_price', 'review_data', 'excluded']) }),
    reviewReasons: strings,
});

// Validate every field read by the view-model before exposing a response to it.
// Other contract fields are preserved untouched; this is not a scoring engine.
const renderable = z.object({
    schemaVersion: z.literal('propicks-unified-v1'), status, asOf: z.string(),
    blocks: z.object({ quality: block, valuation: block, dca: block, tracking: block }),
    items: z.array(pick),
});

export function hasRenderableUnifiedShape(value: unknown): boolean {
    return renderable.safeParse(value).success;
}
