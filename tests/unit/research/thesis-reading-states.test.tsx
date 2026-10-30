import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getResearchCompanySnapshot, getResearchThesisWorkspace } from '@/lib/actions/research.actions';
import { researchRequest } from '@/lib/research/client';
import ThesisReadingPage from '@/app/(root)/research/[ticker]/tesis/page';
import { AppError } from '@/lib/types/errors';

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

beforeEach(() => {
    vi.mocked(getResearchCompanySnapshot).mockResolvedValue({ company: { name: 'Apple', currency: 'USD' }, model_summary: { publishable: true, status: 'ok' } } as never);
    vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis } as never);
    vi.mocked(researchRequest).mockResolvedValue([thesis]);
});

describe('vista de lectura de la tesis: estados honestos', () => {
    it('si el workspace falla, dice que no se pudo cargar y no que no haya tesis', async () => {
        vi.mocked(getResearchThesisWorkspace).mockRejectedValue(new Error('500'));
        render(await page());
        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByRole('heading', { level: 1, name: 'No se pudo cargar la tesis de AAPL' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Reintentar' })).toHaveAttribute('href', '/research/AAPL/tesis');
        expect(screen.queryByText(/Aún no hay ninguna tesis publicada/)).not.toBeInTheDocument();
        expect(screen.queryByText(/Todavía no se ha generado/)).not.toBeInTheDocument();
    });

    it('si fallan las versiones (aunque haya última), tampoco se presenta como «sin publicada»', async () => {
        vi.mocked(researchRequest).mockRejectedValue(new Error('timeout'));
        render(await page());
        expect(screen.getByRole('heading', { level: 1, name: 'No se pudo cargar la tesis de AAPL' })).toBeInTheDocument();
        expect(screen.queryByText(/Aún no hay ninguna tesis publicada/)).not.toBeInTheDocument();
    });

    it('sin snapshot no se puede evaluar la puerta de publicación: error, no texto retenido', async () => {
        vi.mocked(getResearchCompanySnapshot).mockRejectedValue(new Error('500'));
        render(await page());
        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.queryByText('Resumen de prueba')).not.toBeInTheDocument();
    });

    it('ticker fuera del master (snapshot y versiones 404): dice que no está en la cobertura, no que el servicio falló', async () => {
        vi.mocked(getResearchCompanySnapshot).mockResolvedValue(null);
        vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis: null } as never);
        vi.mocked(researchRequest).mockRejectedValue(new AppError('Company not found', 'RESEARCH_API_ERROR', 404));
        render(await page());
        expect(screen.getByRole('heading', { level: 1, name: 'No hay tesis de AAPL' })).toBeInTheDocument();
        expect(screen.getByText(/AAPL no está en la cobertura verificada de GerarAI/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Comprobar AAPL en su ficha' })).toHaveAttribute('href', '/research/AAPL');
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(screen.queryByText(/no respondió/)).not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'Reintentar' })).not.toBeInTheDocument();
    });

    it('un fallo real de /versions (no 404) sigue siendo error aunque falte el snapshot', async () => {
        vi.mocked(getResearchCompanySnapshot).mockResolvedValue(null);
        vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis } as never);
        vi.mocked(researchRequest).mockRejectedValue(new AppError('boom', 'RESEARCH_API_ERROR', 503));
        render(await page());
        expect(screen.getByRole('heading', { level: 1, name: 'No se pudo cargar la tesis de AAPL' })).toBeInTheDocument();
    });

    it('sin ninguna tesis (404 = thesis null) sigue el estado vacío con su siguiente paso', async () => {
        vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis: null } as never);
        vi.mocked(researchRequest).mockResolvedValue([]);
        render(await page());
        expect(screen.getByRole('heading', { level: 1, name: 'Aún no hay ninguna tesis publicada de AAPL.' })).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
});

describe('vista de lectura de la tesis: documento', () => {
    it('índice con anclas a cada sección que existe, en el orden del documento', async () => {
        render(await page());
        const [toc] = screen.getAllByRole('navigation', { name: 'Índice de la tesis' });
        const links = within(toc).getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')]);
        expect(links).toEqual([
            ['Resumen ejecutivo', '#resumen'],
            ['Hipótesis', '#hipotesis'],
            ['Escenarios y valoración', '#escenarios'],
            ['Procedencia de las cifras', '#procedencia'],
            ['Negocio', '#seccion-1'],
            ['Riesgos', '#seccion-2'],
            ['Catalizadores', '#catalizadores'],
            ['Qué invalidaría la tesis', '#invalidacion'],
        ]);
        for (const [, href] of links) {
            expect(document.getElementById(href!.slice(1))).not.toBeNull();
        }
    });

    it('cada fuente se lee por su dominio, no como un número suelto', async () => {
        render(await page());
        const source = screen.getByRole('link', { name: /Fuente 1 de .*: sec\.gov/ });
        expect(source).toHaveTextContent('sec.gov');
        expect(source).toHaveAttribute('href', 'https://www.sec.gov/doc');
    });

    it('rating and version use the print metadata contrast hook', async () => {
        render(await page());
        expect(screen.getByText('Rating: mantener')).toHaveClass('thesis-meta-badge');
        expect(screen.getByText('v4')).toHaveClass('thesis-meta-badge');
    });

    it('cifras de la valoración como lista de definiciones con su etiqueta', async () => {
        render(await page());
        expect(screen.getByText('Valor esperado').nextElementSibling).toHaveTextContent(/110/);
        expect(screen.getByText('Margen de seguridad')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute('href', '/api/thesis/AAPL/pdf');
    });

    it('A10: una tesis antigua solo con markdown muestra sus catalizadores y riesgos en la lectura', async () => {
        const old = {
            ...thesis, narrative_sections: [], catalysts: [], invalidation_criteria: [],
            thesis_markdown: '# ACME\n\n## Catalizadores\n\n- Investor day en enero\n\n## Riesgos\n\nLa deuda vence en 2027.\n',
        };
        vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis: old } as never);
        vi.mocked(researchRequest).mockResolvedValue([old]);
        render(await page());
        expect(screen.getAllByRole('heading', { name: 'Catalizadores' }).length).toBeGreaterThan(0);
        expect(screen.getByText('Investor day en enero')).toBeInTheDocument();
        expect(screen.getAllByRole('heading', { name: 'Riesgos' }).length).toBeGreaterThan(0);
        expect(screen.getByText('La deuda vence en 2027.')).toBeInTheDocument();
    });
});
