import { describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ auth: vi.fn(), request: vi.fn(), revalidate: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: mocks.auth }));
vi.mock('@/lib/research/client', () => ({ researchRequest: mocks.request }));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidate }));
import { addPlanContribution, deletePlanContribution } from '@/lib/actions/plan.actions';

describe('aportaciones del plan (server actions)', () => {
    it('registra la aportación con la divisa en mayúsculas y refresca /plan', async () => {
        mocks.auth.mockResolvedValue({ id: 'u' }); mocks.request.mockResolvedValue({ id: 1 });
        expect(await addPlanContribution({ date: '2026-10-01', amount: 300, currency: 'eur', note: 'octubre' })).toEqual({ ok: true });
        expect(mocks.request).toHaveBeenCalledWith('/api/plan/contributions', {
            method: 'POST', body: '{"date":"2026-10-01","amount":300,"currency":"EUR","note":"octubre"}',
        });
        expect(mocks.revalidate).toHaveBeenCalledWith('/plan');
    });
    it('un rechazo del backend vuelve como mensaje, no como excepción', async () => {
        mocks.auth.mockResolvedValue({ id: 'u' }); mocks.request.mockRejectedValueOnce(new Error('400'));
        const result = await addPlanContribution({ date: '2026-10-01', amount: 300, currency: 'EUR' });
        expect(result.ok).toBe(false);
    });
    it('borra por id entero y rechaza ids raros sin llamar al backend', async () => {
        mocks.auth.mockResolvedValue({ id: 'u' }); mocks.request.mockReset(); mocks.request.mockResolvedValue(undefined);
        expect(await deletePlanContribution(7)).toEqual({ ok: true });
        expect(mocks.request).toHaveBeenCalledWith('/api/plan/contributions/7', { method: 'DELETE' });
        mocks.request.mockClear();
        expect((await deletePlanContribution(1.5)).ok).toBe(false);
        expect((await deletePlanContribution(-1)).ok).toBe(false);
        expect(mocks.request).not.toHaveBeenCalled();
    });
});
