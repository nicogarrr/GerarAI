import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest } = vi.hoisted(() => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));

import { getGems, reviewGems } from '@/lib/actions/propicks-gems.actions';
import { getTrackRecord } from '@/lib/actions/propicks-track-record.actions';

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('getGems / reviewGems', () => {
    it('gems: lista tal cual del backend', async () => {
        researchRequest.mockResolvedValue([{ ticker: 'AAPL', score: 80 }]);
        expect(await getGems()).toEqual([{ ticker: 'AAPL', score: 80 }]);
        expect(researchRequest).toHaveBeenCalledWith('/api/propicks/gems?limit=20', { fast: true });
    });

    it('gems caído -> { error } sin lanzar', async () => {
        researchRequest.mockRejectedValue(new Error('500'));
        expect(await getGems()).toEqual({ error: 'No se pudieron cargar las joyas.' });
    });

    it('review: POST con timeout largo (cadena gratuita LLM)', async () => {
        researchRequest.mockResolvedValue([{ ticker: 'AAPL', review_status: 'reviewed' }]);
        expect(await reviewGems()).toEqual([{ ticker: 'AAPL', review_status: 'reviewed' }]);
        expect(researchRequest).toHaveBeenCalledWith('/api/propicks/review?limit=20', { method: 'POST', timeoutMs: 55_000 });
    });

    it('review caído -> { error }', async () => {
        researchRequest.mockRejectedValue(new Error('timeout'));
        expect(await reviewGems()).toEqual({ error: 'No se pudo completar la revisión.' });
    });
});

describe('getTrackRecord', () => {
    it('devuelve el histórico; caído -> { error }', async () => {
        researchRequest.mockResolvedValue({ snapshots_count: 3, picks: [] });
        expect(await getTrackRecord()).toEqual({ snapshots_count: 3, picks: [] });
        researchRequest.mockRejectedValue(new Error('500'));
        expect(await getTrackRecord()).toEqual({ error: 'No se pudo cargar el histórico de selecciones.' });
    });
});
