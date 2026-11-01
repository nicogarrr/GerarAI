import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getResearchCompanySnapshot, getResearchThesisWorkspace } from '@/lib/actions/research.actions';
import { researchRequest } from '@/lib/research/client';
import ThesisReadingPage from '@/app/(root)/research/[ticker]/tesis/page';

vi.mock('@/lib/actions/research.actions', () => ({ getResearchCompanySnapshot: vi.fn(), getResearchThesisWorkspace: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/public-fonts-editorial', () => ({ publicEditorial: { variable: '' } }));
vi.mock('@/components/research/PrintButton', () => ({ default: () => null }));
const i18n = vi.hoisted(() => ({ locale: 'en' as 'es' | 'en' }));
vi.mock('@/lib/i18n/server', async () => {
    const { createTranslator } = await import('@/lib/i18n/translate');
    return { getLocale: async () => i18n.locale, getT: async () => createTranslator(i18n.locale) };
});

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

beforeEach(() => {
    vi.mocked(getResearchCompanySnapshot).mockResolvedValue({ company: { name: 'Apple', currency: 'USD' }, model_summary: { publishable: true, status: 'ok' } } as never);
    vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis } as never);
    vi.mocked(researchRequest).mockResolvedValue([thesis]);
});

describe('vista de lectura de la tesis en inglés', () => {
    it('títulos, tabla, importes y procedencia en inglés', async () => {
        i18n.locale = 'en';
        render(await page());
        expect(screen.getByText('Investment thesis')).toBeInTheDocument();
        expect(screen.getByText('Rating: hold')).toBeInTheDocument();
        expect(screen.getAllByText('Scenarios and valuation').length).toBeGreaterThan(0);
        expect(screen.getByText('Value per share')).toBeInTheDocument();
        expect(screen.getByText('Bear')).toBeInTheDocument();
        expect(screen.getAllByText('$110.00').length).toBeGreaterThan(0);
        expect(screen.getByText('Expected value')).toBeInTheDocument();
        expect(screen.getByText('Margin of safety')).toBeInTheDocument();
        expect(screen.getByText('Reported')).toBeInTheDocument();
        expect(screen.getByText(/Evidence quality: data confidence 70\/100/)).toBeInTheDocument();
        expect(screen.queryByText(/Escenarios|Valor por acción|Bajista|Calidad de la evidencia|Reportado/)).not.toBeInTheDocument();
    });
    it('sin tesis publicada: estado vacío en inglés', async () => {
        i18n.locale = 'en';
        vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis: null } as never);
        vi.mocked(researchRequest).mockResolvedValue([]);
        render(await page());
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('No published thesis for AAPL yet.');
        expect(screen.getByText('Generate the first thesis from the overview')).toBeInTheDocument();
    });
    it('en español no cambia', async () => {
        i18n.locale = 'es';
        render(await page());
        expect(screen.getByText('Rating: mantener')).toBeInTheDocument();
        expect(screen.getByText('Valor por acción')).toBeInTheDocument();
        expect(screen.getAllByText(/^110,00\sUS\$$/).length).toBeGreaterThan(0);
    });
});
