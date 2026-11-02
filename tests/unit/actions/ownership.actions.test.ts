import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.hoisted(() => {
    // El job de CI fija FMP_BACKEND_URL=http://127.0.0.1:8000 para el build y los
    // guards. Estos tests verifican el mapa de constantes por defecto
    // (http://localhost:8000), asi que fijan el entorno antes de que se importen
    // los modulos de acciones, que leen BACKEND_URL en ambito de modulo.
    process.env.FMP_BACKEND_URL = 'http://localhost:8000';
});

const { normalizeResearchBody, researchIdentityHeaders, revalidatePath } = vi.hoisted(() => ({
    normalizeResearchBody: vi.fn(async (body: unknown) => ({ body, contentType: null })),
    researchIdentityHeaders: vi.fn(async () => ({ 'X-Tenant': 'user-1' })),
    revalidatePath: vi.fn(),
}));
vi.mock('@/lib/auth/research-identity', () => ({ normalizeResearchBody, researchIdentityHeaders }));
vi.mock('next/cache', () => ({ revalidatePath }));

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

import { getOwnershipManagers, getManagerHoldings, getManagerChanges, syncOwnershipManagers } from '@/lib/actions/ownership.actions';

beforeEach(() => { vi.clearAllMocks(); });

describe('ownership 13F', () => {
    it('CIK codificado en la ruta', async () => {
        fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
        await getManagerHoldings('0001067983');
        expect(String(fetchMock.mock.calls[0][0])).toBe('http://localhost:8000/api/ownership/managers/0001067983/holdings');
        await getManagerChanges('0001067983');
        expect(String(fetchMock.mock.calls[1][0])).toContain('/changes');
        await getOwnershipManagers();
        expect(String(fetchMock.mock.calls[2][0])).toContain('/api/ownership/managers');
    });

    it('no-ok -> ExternalAPIError con el status; red caída -> envuelta', async () => {
        fetchMock.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) } as Response);
        await expect(getManagerHoldings('x')).rejects.toMatchObject({ code: 'RESEARCH_API_ERROR', statusCode: 404 });
        fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
        await expect(getManagerHoldings('x')).rejects.toMatchObject({ code: 'EXTERNAL_API_ERROR', message: expect.stringContaining('unavailable') });
    });

    it('sync -> POST y revalida /ownership', async () => {
        fetchMock.mockResolvedValue({ ok: true, json: async () => ({ results: [] }) } as Response);
        expect(await syncOwnershipManagers()).toEqual({ results: [] });
        expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' });
        expect(revalidatePath).toHaveBeenCalledWith('/ownership');
    });
});
