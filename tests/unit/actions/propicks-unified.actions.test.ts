import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest } = vi.hoisted(() => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));

import { AppError, ExternalAPIError } from '@/lib/types/errors';
import { getUnifiedProPicks } from '@/lib/actions/propicks-unified.actions';
import { deriveUnifiedViewState, toOpportunityRow } from '@/lib/propicks/unified';
import type { components } from '@/lib/research/openapi.generated';

type UnifiedResult = components['schemas']['UnifiedResult'];
type UnifiedPick = components['schemas']['UnifiedPick'];
type Datum = components['schemas']['Datum'];

const datum = (status: Datum['status'], value: number | string | null = null): Datum => ({
    status,
    value,
    reasonCodes: [],
});

const listing = (over: Partial<UnifiedPick['listing']> = {}): UnifiedPick['listing'] => ({
    ticker: 'TEST',
    name: 'Empresa de prueba',
    status: 'unknown',
    identityStatus: 'unverified',
    identityEvidence: [],
    identityReasonCodes: [],
    tradingStatus: 'unknown',
    instrumentStatus: 'unknown',
    issuerLegalStatus: 'unknown',
    ...over,
});

const pick = (over: Partial<UnifiedPick> = {}): UnifiedPick => ({
    instrumentId: 'TEST',
    listing: listing(),
    quality: {
        passed: true,
        score: datum('ok', 73),
        policyVersion: 'quality-v1',
        scorePolicyVersion: 'propicks-funnel-v1',
        coverage: { present: 5, required: 5, total: 5 },
        reasonCodes: [],
    },
    valuation: {
        status: 'missing',
        price: datum('missing'),
        fcfYield: datum('missing'),
        priceToBook: datum('missing'),
        marginOfSafety: datum('missing'),
    },
    dca: {
        status: 'ok',
        level: datum('ok', 3),
        periodState: 'confirmed',
        confirmedLevel: datum('ok', 3),
    },
    tracking: { held: false, watched: true },
    eligibility: { state: 'investigate', reasonCodes: [] },
    evidenceFlags: [],
    reviewReasons: [],
    asOf: '2026-11-15',
    ...over,
});

const result = (over: Partial<UnifiedResult> = {}): UnifiedResult => ({
    schemaVersion: 'propicks-unified-v1',
    status: 'ok',
    asOf: '2026-11-15',
    coverage: {},
    blocks: {
        quality: { status: 'ok', asOf: '2026-11-15' },
        valuation: { status: 'ok', asOf: '2026-11-15' },
        dca: { status: 'ok', asOf: '2026-11-15' },
        tracking: { status: 'ok', asOf: '2026-11-15' },
    },
    items: [pick()],
    ...over,
});

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('getUnifiedProPicks: contrato propicks-unified-v1', () => {
    it('pide /api/propicks/unified y devuelve el resultado tal cual', async () => {
        researchRequest.mockResolvedValue(result());
        const r = await getUnifiedProPicks();
        expect(researchRequest).toHaveBeenCalledWith('/api/propicks/unified', expect.anything());
        expect(r).toEqual({ ok: true, result: expect.objectContaining({ schemaVersion: 'propicks-unified-v1' }) });
    });

    it('schemaVersion distinta -> invalid_response, nunca se interpreta', async () => {
        researchRequest.mockResolvedValue({ ...result(), schemaVersion: 'propicks-unified-v0' });
        const r = await getUnifiedProPicks();
        expect(r).toEqual({ ok: false, errorKind: 'invalid_response', retryAfterSeconds: null });
    });

    it('429 -> rate_limited con retryAfterSeconds; 401 -> unauthenticated; 403 -> forbidden; 5xx -> unavailable', async () => {
        researchRequest.mockRejectedValueOnce(new AppError('rate', 'RESEARCH_API_ERROR', 429, { retryAfterSeconds: 7 }));
        expect(await getUnifiedProPicks()).toEqual({ ok: false, errorKind: 'rate_limited', retryAfterSeconds: 7 });
        researchRequest.mockRejectedValueOnce(new AppError('auth', 'RESEARCH_API_ERROR', 401, {}));
        expect(await getUnifiedProPicks()).toEqual({ ok: false, errorKind: 'unauthenticated', retryAfterSeconds: null });
        researchRequest.mockRejectedValueOnce(new AppError('deny', 'RESEARCH_API_ERROR', 403, {}));
        expect(await getUnifiedProPicks()).toEqual({ ok: false, errorKind: 'forbidden', retryAfterSeconds: null });
        researchRequest.mockRejectedValueOnce(new AppError('down', 'RESEARCH_API_ERROR', 503, {}));
        expect(await getUnifiedProPicks()).toEqual({ ok: false, errorKind: 'unavailable', retryAfterSeconds: null });
    });

    it('timeout del motor -> timeout; otro fallo de red -> unavailable', async () => {
        researchRequest.mockRejectedValueOnce(new ExternalAPIError('Research engine unavailable for /api/propicks/unified (timeout de 15000 ms); reintenta en unos segundos.', 'research-engine'));
        expect(await getUnifiedProPicks()).toEqual({ ok: false, errorKind: 'timeout', retryAfterSeconds: null });
        researchRequest.mockRejectedValueOnce(new ExternalAPIError('Research engine unavailable for /api/propicks/unified (fetch fallido); reintenta en unos segundos.', 'research-engine'));
        expect(await getUnifiedProPicks()).toEqual({ ok: false, errorKind: 'unavailable', retryAfterSeconds: null });
    });
});

describe('deriveUnifiedViewState: el estado sale del contrato', () => {
    it('ok -> ok; empty -> empty', () => {
        expect(deriveUnifiedViewState(result())).toEqual({ state: 'ok', affectedBlocks: [], asOf: '2026-11-15' });
        expect(deriveUnifiedViewState(result({ status: 'empty', items: [] })).state).toBe('empty');
    });

    it('partial -> affectedBlocks solo con los bloques no-ok, en orden del contrato', () => {
        const r = result({
            status: 'partial',
            blocks: {
                quality: { status: 'ok', asOf: '2026-11-15' },
                valuation: { status: 'error', error: { kind: 'timeout' }, asOf: null },
                dca: { status: 'partial', asOf: '2026-11-15' },
                tracking: { status: 'ok', asOf: '2026-11-15' },
            },
        });
        expect(deriveUnifiedViewState(r)).toEqual({ state: 'partial', affectedBlocks: ['valuation', 'dca'], asOf: '2026-11-15' });
    });

    it('error en el resultado -> state error con el kind del primer bloque con error', () => {
        const r = result({
            status: 'error',
            items: [],
            blocks: {
                quality: { status: 'error', error: { kind: 'unavailable' }, asOf: null },
                valuation: { status: 'error', error: { kind: 'timeout' }, asOf: null },
                dca: { status: 'error', error: { kind: 'timeout' }, asOf: null },
                tracking: { status: 'error', error: { kind: 'timeout' }, asOf: null },
            },
        });
        expect(deriveUnifiedViewState(r)).toMatchObject({ state: 'error', errorKind: 'unavailable' });
    });
});

describe('toOpportunityRow: ausencia como ausencia, nunca 0/50', () => {
    it('score de calidad del contrato (73) y valoración ausente sin número', () => {
        const row = toOpportunityRow(pick());
        expect(row.ticker).toBe('TEST');
        expect(row.qualityScore).toBe(73);
        expect(row.qualityPassed).toBe(true);
        expect(row.valuationStatus).toBe('missing');
        expect(row.valuationPrice).toBeNull();
        expect(row.marginOfSafety).toBeNull();
        expect(row.dcaLevel).toBe(3);
        expect(row.dcaPeriodState).toBe('confirmed');
        expect(row.eligibility).toBe('investigate');
        expect(row.asOf).toBe('2026-11-15');
    });

    it('score stale o invalid -> null declarado, no el valor viejo ni 0', () => {
        const stale = toOpportunityRow(pick({ quality: { ...pick().quality, score: datum('stale') } }));
        expect(stale.qualityScore).toBeNull();
        const zero = toOpportunityRow(pick({ quality: { ...pick().quality, score: datum('ok', 0) } }));
        expect(zero.qualityScore).toBe(0); // el 0 REAL sí se muestra
    });

    it('reasonCodes de calidad y revisión se conservan para el aviso', () => {
        const p = pick({
            quality: { ...pick().quality, reasonCodes: ['valuation_stale'] },
            reviewReasons: ['identity_unverified'],
        });
        const row = toOpportunityRow(p);
        expect(row.reasonCodes).toEqual(['valuation_stale', 'identity_unverified']);
    });

    it('instrumento cancelado o negociación suspendida llegan como reasonCodes de listing', () => {
        const p = pick({
            listing: listing({ status: 'active', instrumentStatus: 'cancelled', tradingStatus: 'suspended' }),
            eligibility: { state: 'excluded', reasonCodes: ['instrument_cancelled'] },
        });
        const row = toOpportunityRow(p);
        expect(row.eligibility).toBe('excluded');
        expect(row.reasonCodes).toContain('instrument_cancelled');
        expect(row.reasonCodes).toContain('trading_suspended');
    });
});


describe('malformed responses are rejected before view-model access', () => {
    it.each([
        null, {}, { schemaVersion: 'propicks-unified-v1' },
        result({ blocks: null as unknown as UnifiedResult['blocks'] }),
        result({ items: {} as unknown as UnifiedPick[] }),
        result({ items: [pick({ reviewReasons: null as unknown as string[] })] }),
        result({ items: [pick({ quality: { ...pick().quality, reasonCodes: null as unknown as string[] } })] }),
        result({ items: [pick({ listing: listing({ ticker: 42 as unknown as string }) })] }),
        result({ items: [pick({ dca: { ...pick().dca, level: datum('ok', Infinity) } })] }),
    ])('returns invalid_response for malformed payload %#', async (payload) => {
        researchRequest.mockResolvedValue(payload);
        expect(await getUnifiedProPicks()).toEqual({ ok: false, errorKind: 'invalid_response', retryAfterSeconds: null });
    });
    it('rejects a missing block even when the schema version matches', async () => {
        const payload = result();
        delete (payload.blocks as Partial<UnifiedResult['blocks']>).tracking;
        researchRequest.mockResolvedValue(payload);
        expect(await getUnifiedProPicks()).toMatchObject({ ok: false, errorKind: 'invalid_response' });
    });
    it('classifies primitive errors and absent retry headers without inventing seconds', async () => {
        researchRequest.mockRejectedValueOnce('offline');
        expect(await getUnifiedProPicks()).toMatchObject({ ok: false, errorKind: 'unavailable' });
        researchRequest.mockRejectedValueOnce(new AppError('rate', 'RESEARCH_API_ERROR', 429, {}));
        expect(await getUnifiedProPicks()).toMatchObject({ ok: false, retryAfterSeconds: null });
    });
});
