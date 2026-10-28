import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, researchIdentityHeaders, revalidatePath } = vi.hoisted(() => ({
    researchRequest: vi.fn(async () => ({})),
    requireAuthenticatedUser: vi.fn(async () => ({ id: 'user-1' })),
    researchIdentityHeaders: vi.fn(async () => ({ 'X-Tenant': 'user-1' })),
    revalidatePath: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));
vi.mock('next/cache', () => ({ revalidatePath }));

import { getLlmSettings, saveLlmSettings, testLlmConnection } from '@/lib/actions/llm-settings.actions';
import { getIBKRConnection, connectIBKR, syncIBKR, disconnectIBKR } from '@/lib/actions/ibkr-settings.actions';
import { getPlan, getPlanContributions, getPlanDrift, getPlanContributionSplit, upsertPlan } from '@/lib/actions/plan.actions';
import { exportJournal } from '@/lib/actions/export.actions';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

beforeEach(() => {
    vi.resetAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
    researchRequest.mockResolvedValue({});
    researchIdentityHeaders.mockResolvedValue({ 'X-Tenant': 'user-1' });
});

describe('llm-settings: la clave nunca viaja al navegador', () => {
    it('lectura sin caché; guardado PUT; test con timeout de 15 s', async () => {
        await getLlmSettings();
        expect(researchRequest).toHaveBeenCalledWith('/api/settings/llm', { cache: 'no-store' });
        await saveLlmSettings({ provider: 'openai', model: 'gpt-5', enabled: true });
        expect(researchRequest).toHaveBeenCalledWith('/api/settings/llm', { method: 'PUT', body: JSON.stringify({ provider: 'openai', model: 'gpt-5', enabled: true }) });
        await testLlmConnection({ provider: 'openai', model: 'gpt-5' });
        expect(researchRequest).toHaveBeenCalledWith('/api/settings/llm/test', expect.objectContaining({ method: 'POST', timeoutMs: 15000 }));
    });
});

describe('ibkr-settings: fallos con mensaje honesto y datos conservados', () => {
    it('connect falla -> ok false con guía; sync falla conserva datos anteriores', async () => {
        researchRequest.mockRejectedValue(new Error('401'));
        expect(await connectIBKR({ token: 't', query_id: 'q', account_id: 'a', complete_query: true })).toMatchObject({ ok: false, message: expect.stringContaining('mismo cierre') });
        expect(await syncIBKR()).toMatchObject({ ok: false, message: expect.stringContaining('Conservamos los datos anteriores') });
        expect(await disconnectIBKR()).toMatchObject({ ok: false, message: expect.stringContaining('puede seguir activa') });
    });

    it('sync ok revalida cartera e inicio', async () => {
        researchRequest.mockResolvedValue({ connected: true });
        expect(await syncIBKR()).toMatchObject({ ok: true });
        expect(revalidatePath).toHaveBeenCalledWith('/portfolio');
        expect(revalidatePath).toHaveBeenCalledWith('/inicio');
    });

    it('getIBKRConnection sin caché', async () => {
        await getIBKRConnection();
        expect(researchRequest).toHaveBeenCalledWith('/api/settings/ibkr', { cache: 'no-store' });
    });
});

describe('plan: stub honesto y rechazos de divisa', () => {
    it('plan_exists false -> null (la UI pinta su estado vacío, no un stub crudo)', async () => {
        researchRequest.mockResolvedValue({ plan_exists: false });
        expect(await getPlan()).toBeNull();
        expect(await getPlanDrift()).toBeNull();
        researchRequest.mockResolvedValue({ plan_exists: true, monthly_contribution: 500 });
        expect(await getPlan()).toMatchObject({ plan_exists: true });
    });

    it('contribution-split: forma inválida o backend caído -> null, /plan no rompe', async () => {
        researchRequest.mockResolvedValue({ no_es: 'un split' });
        expect(await getPlanContributionSplit()).toBeNull();
        researchRequest.mockRejectedValue(new Error('404'));
        expect(await getPlanContributionSplit()).toBeNull();
    });

    it('getPlanContributions pasa tal cual', async () => {
        researchRequest.mockResolvedValue([{ amount: 500 }]);
        expect(await getPlanContributions()).toEqual([{ amount: 500 }]);
    });

    it('409 de divisa -> resultado con código, no excepción enmascarada; otro error propaga', async () => {
        researchRequest.mockRejectedValue(new Error('Conflict: plan_currency_required_for_amount_change'));
        expect(await upsertPlan({ monthly_contribution: 500, start_date: '2026-01-01', horizon_years: 20, target_allocations: [] }))
            .toEqual({ ok: false, code: 'plan_currency_required_for_amount_change' });
        researchRequest.mockRejectedValue(new Error('plan_currency_contract_disabled'));
        expect(await upsertPlan({ monthly_contribution: 500, start_date: '2026-01-01', horizon_years: 20, target_allocations: [] }))
            .toEqual({ ok: false, code: 'plan_currency_contract_disabled' });
        researchRequest.mockRejectedValue(new Error('500 boom'));
        await expect(upsertPlan({ monthly_contribution: 500, start_date: '2026-01-01', horizon_years: 20, target_allocations: [] })).rejects.toThrow('boom');
    });

    it('upsert ok revalida /plan', async () => {
        expect(await upsertPlan({ monthly_contribution: 500, start_date: '2026-01-01', horizon_years: 20, target_allocations: [] })).toEqual({ ok: true });
        expect(revalidatePath).toHaveBeenCalledWith('/plan');
    });
});

describe('exportJournal: request-forgery cerrado y errores sin trazas', () => {
    it('año fuera de 2000-2100 o no entero -> ValidationError antes de llamar', async () => {
        await expect(exportJournal(1999)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await expect(exportJournal(2101)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await expect(exportJournal(2024.5)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('formato no union en runtime -> ValidationError', async () => {
        await expect(exportJournal(2024, 'xml' as never)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('la URL sale del mapa de constantes con el formato revalidado', async () => {
        fetchMock.mockResolvedValue({ ok: true, headers: new Headers({ 'content-type': 'text/csv' }), text: async () => 'a,b' } as unknown as Response);
        const result = await exportJournal(2024, 'csv');
        expect(String(fetchMock.mock.calls[0][0])).toBe('http://localhost:8000/api/export/2024?format=csv');
        expect(result).toEqual({ filename: 'journal-2024.csv', contentType: 'text/csv', content: 'a,b' });
        await exportJournal(2024, 'json');
        expect(String(fetchMock.mock.calls[1][0])).toContain('format=json');
    });

    it('backend no-ok -> error público con status; el cuerpo NUNCA se loguea ni se devuelve', async () => {
        const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        fetchMock.mockResolvedValue({ ok: false, status: 500, text: async () => 'TRAZA INTERNA SQL apikey=secreta' } as unknown as Response);
        await expect(exportJournal(2024)).rejects.toMatchObject({ code: 'RESEARCH_API_ERROR', statusCode: 500, message: 'Exportación falló (500)' });
        const logged = consoleSpy.mock.calls.flat().join(' ');
        expect(logged).not.toContain('TRAZA');
        expect(logged).not.toContain('apikey');
        expect(logged).toContain('500');
    });
});
