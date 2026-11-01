import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getResearchCompanySnapshot, getResearchThesisWorkspace } from '@/lib/actions/research.actions';
import { researchRequest } from '@/lib/research/client';
import ThesisReadingPage from '@/app/(root)/research/[ticker]/tesis/page';
import { AppError } from '@/lib/types/errors';

vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('@/lib/actions/research.actions', () => ({ getResearchCompanySnapshot: vi.fn(), getResearchThesisWorkspace: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/public-fonts-editorial', () => ({ publicEditorial: { variable: '' } }));
vi.mock('@/components/research/PrintButton', () => ({ default: () => null }));

const thesis = {
    id: 7, version: 4, status: 'published', rating: 'hold', created_at: '2026-10-19T06:54:00Z',
    executive_summary: 'Resumen de prueba', hypothesis: 'Hipótesis de prueba',
    narrative_sections: [{ titulo: 'Negocio', parrafos: ['Uno', 'Dos'] }, { titulo: 'Riesgos', parrafos: ['Tres'] }],
    catalysts: [{ label: 'Resultados' }], invalidation_criteria: ['Margen cae'],
    current_price: '100', bear_value: '80', base_value: '110', bull_value: '140', expected_value: '110',
    margin_of_safety: '0.09', scenario_probabilities: null, valuation_basis: null,
    data_confidence_score: 70, source_coverage_score: 60, red_team_score: 50,
    inputs_provenance: [{ key: 'revenue', label: 'dato', origen: 'OFICIAL', value: 100, unit: 'USD', method: 'filing', fuentes: [{ url: 'https://www.sec.gov/doc', oficial: true, fecha: '2026-02-01' }] }],
};

const page = () => ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }) });

const experts = {
    ticker: 'AAPL', run_id: 3, finished_at: '2026-11-01T20:00:00Z', plan: ['fundamental', 'risk'],
    sections: [
        { expert: 'fundamental', status: 'ok', summary: 'Sólido', stance: 'bullish', claims: [{ text: 'Ingresos al alza', refs: [1] }] },
        { expert: 'risk', status: 'timeout', summary: '', stance: 'neutral', claims: [] },
    ],
    sources: [{ n: 1, title: 'Estados financieros · SEC EDGAR · FY · 2025', url: 'https://www.sec.gov/Archives/edgar/data/320193/x-index.htm' }],
    conflicts: [], verdict: null,
};

function backend(expertPayload: unknown) {
    vi.mocked(researchRequest).mockImplementation(async (path: string) => {
        if (path.endsWith('/experts')) {
            if (expertPayload instanceof Error) throw expertPayload;
            return expertPayload as never;
        }
        return [thesis] as never;
    });
}

beforeEach(() => {
    vi.mocked(getResearchCompanySnapshot).mockResolvedValue({ company: { name: 'Apple', currency: 'USD' }, model_summary: { publishable: true, status: 'ok' } } as never);
    vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis } as never);
});

describe('vista de lectura de la tesis: tesis del equipo de expertos', () => {
    it('si hay una guardada, se ve debajo de la tesis con sus secciones y fuentes', async () => {
        backend(experts);
        render(await page());
        const panel = screen.getByTestId('expert-thesis');
        expect(panel).toHaveTextContent('Tesis del equipo de expertos');
        expect(within(panel).getByTestId('expert-thesis-fundamental')).toHaveTextContent('Ingresos al alza');
        expect(within(panel).getByRole('link', { name: /SEC EDGAR/ })).toHaveAttribute('href', 'https://www.sec.gov/Archives/edgar/data/320193/x-index.htm');
        // La tesis de siempre sigue ahí.
        expect(screen.getAllByText('Resumen de prueba').length).toBeGreaterThan(0);
    });

    it('con el equipo apagado (404) o sin ninguna, la página no cambia', async () => {
        backend(new AppError('Not found', 'NOT_FOUND', 404));
        render(await page());
        expect(screen.queryByTestId('expert-thesis')).toBeNull();
        expect(screen.getAllByText('Resumen de prueba').length).toBeGreaterThan(0);
    });
});

describe('vista de lectura de la tesis: abrir una corrida anterior del equipo', () => {
    it('?expertRun=N pide esa corrida y la pinta entera', async () => {
        const older = { ...experts, run_id: 2, is_latest: false, history: [{ run_id: 3, finished_at: '2026-11-01T20:00:00Z', verdict: null, answered: [], timed_out: [] }] };
        vi.mocked(researchRequest).mockImplementation(async (path: string) => {
            if (path.endsWith('/experts?run=2')) return older as never;
            if (path.includes('/experts')) throw new Error(`no esperado: ${path}`);
            return [thesis] as never;
        });
        render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }), searchParams: Promise.resolve({ expertRun: '2' }) }));
        expect(screen.getByTestId('expert-thesis-older')).toHaveTextContent('Estás viendo una corrida anterior');
        expect(within(screen.getByTestId('expert-thesis-run-3')).getByRole('link')).toHaveAttribute('href', '/research/AAPL/tesis?expertRun=3#expert-thesis');
    });

    it('una corrida que no es tuya o no existe (404) vuelve a la última; basura en ?expertRun se ignora', async () => {
        const calls: string[] = [];
        vi.mocked(researchRequest).mockImplementation(async (path: string) => {
            if (path.includes('/experts')) {
                calls.push(path);
                if (path.endsWith('?run=99')) throw new AppError('Not found', 'NOT_FOUND', 404);
                return experts as never;
            }
            return [thesis] as never;
        });
        render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }), searchParams: Promise.resolve({ expertRun: '99' }) }));
        expect(calls).toEqual(['/api/thesis/AAPL/experts?run=99', '/api/thesis/AAPL/experts']);
        expect(screen.getByTestId('expert-thesis')).toBeInTheDocument();
        expect(screen.queryByTestId('expert-thesis-older')).toBeNull();
        calls.length = 0;
        render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }), searchParams: Promise.resolve({ expertRun: '1;drop' }) }));
        expect(calls).toEqual(['/api/thesis/AAPL/experts']);
    });
});
