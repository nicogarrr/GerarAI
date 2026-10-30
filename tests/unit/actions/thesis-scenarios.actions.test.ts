import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, getResearchThesisWorkspace } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    getResearchThesisWorkspace: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest }));
vi.mock('@/lib/actions/research.actions', () => ({ getResearchThesisWorkspace }));

import { getThesisScenarios, getThesisWithScenarios } from '@/lib/actions/thesis-scenarios.actions';

const persisted = {
    ticker: 'BRK-B',
    estado: 'persistido',
    motivo: null,
    fuente: { tabla: 'thesis_scenarios', version: 3, modelo: 'manual', fecha: '2026-10-01' },
    escenarios: {
        bear: { nombre: 'Pesimista', proyecciones: [], motivo: null },
        base: { nombre: 'Base', proyecciones: [], motivo: null },
        bull: { nombre: 'Optimista', proyecciones: [], motivo: null },
    },
    aviso_coherencia: null,
};

describe('getThesisScenarios', () => {
    beforeEach(() => {
        researchRequest.mockReset();
        getResearchThesisWorkspace.mockReset();
    });

    it('pide los escenarios al backend con el ticker codificado en la ruta', async () => {
        researchRequest.mockResolvedValue(persisted);
        const result = await getThesisScenarios('BRK/B');
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/BRK%2FB/thesis-scenarios', { timeoutMs: 12_000 });
        expect(result).toEqual(persisted);
    });

    it('degrada a null cuando el backend falla: los escenarios no tumban la tesis', async () => {
        researchRequest.mockRejectedValue(new Error('backend 500'));
        await expect(getThesisScenarios('AAPL')).resolves.toBeNull();
    });
});

describe('getThesisWithScenarios', () => {
    beforeEach(() => {
        researchRequest.mockReset();
        getResearchThesisWorkspace.mockReset();
    });

    it('combina el workspace con los escenarios persistidos', async () => {
        const workspace = { ticker: 'AAPL', memo: { estado: 'persistido' } };
        getResearchThesisWorkspace.mockResolvedValue(workspace);
        researchRequest.mockResolvedValue(persisted);
        const result = await getThesisWithScenarios('AAPL');
        expect(getResearchThesisWorkspace).toHaveBeenCalledWith('AAPL');
        expect(result).toEqual({ ...workspace, scenarios: persisted });
    });

    it('el workspace llega aunque los escenarios fallen (scenarios: null)', async () => {
        const workspace = { ticker: 'AAPL', memo: { estado: 'persistido' } };
        getResearchThesisWorkspace.mockResolvedValue(workspace);
        researchRequest.mockRejectedValue(new Error('timeout'));
        const result = await getThesisWithScenarios('AAPL');
        expect(result).toEqual({ ...workspace, scenarios: null });
    });
});
