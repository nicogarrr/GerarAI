import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ExpertThesisPanel } from '@/components/research/ExpertThesisPanel';
import type { ExpertThesis } from '@/lib/actions/expert-thesis.actions';
import { createTranslator } from '@/lib/i18n/translate';

const thesis: ExpertThesis = {
    ticker: 'MSFT',
    run_id: 7,
    finished_at: '2026-11-01T20:00:00Z',
    plan: ['fundamental', 'valuation', 'news'],
    sections: [
        { expert: 'fundamental', status: 'ok', summary: 'Crece con margen', stance: 'bullish',
          claims: [{ text: 'Ingresos de 245 mil millones', refs: [1] }, { text: 'Caja neta positiva', refs: [2, 9] }] },
        { expert: 'valuation', status: 'timeout', summary: '', stance: 'neutral', claims: [] },
        { expert: 'news', status: 'no_data', summary: '', stance: 'neutral', claims: [] },
    ],
    sources: [
        { n: 1, title: 'Estados financieros · SEC EDGAR · FY · 2025', url: 'https://www.sec.gov/Archives/edgar/data/789019/x-index.htm' },
        { n: 2, title: 'Estados financieros · FY · 2024', url: 'javascript:alert(1)' },
    ],
    conflicts: ['Fundamental lo ven a favor y Riesgo en contra'],
    verdict: { label: 'a favor', rationale: 'Pesa más el crecimiento.' },
};

describe('tesis guardada del equipo de expertos', () => {
    it('una sección por experto, cada afirmación con su [n] y las fuentes numeradas', () => {
        render(<ExpertThesisPanel thesis={thesis} t={createTranslator('es')} formatDate={() => '1 nov 2026'} />);
        const panel = screen.getByTestId('expert-thesis');
        expect(within(panel).getByRole('heading', { level: 2 })).toHaveTextContent('Tesis del equipo de expertos');
        expect(panel).toHaveTextContent('Generada el 1 nov 2026');
        const fundamental = screen.getByTestId('expert-thesis-fundamental');
        expect(fundamental).toHaveTextContent('Fundamental');
        expect(fundamental).toHaveTextContent('Crece con margen');
        expect(within(fundamental).getByRole('link', { name: '[1]' })).toHaveAttribute('href', '#expert-source-7-1');
        // [9] no existe en las fuentes: no se pinta un enlace roto.
        expect(within(fundamental).queryByRole('link', { name: '[9]' })).toBeNull();
        expect(screen.getByTestId('expert-thesis-valuation')).toHaveTextContent('No respondió a tiempo.');
        expect(screen.getByTestId('expert-thesis-news')).toHaveTextContent('Sin datos suficientes.');
        expect(screen.getByTestId('expert-thesis-verdict')).toHaveTextContent('Veredicto del juez: a favor. Pesa más el crecimiento.');
        expect(panel).toHaveTextContent('Choques entre expertos');
    });

    it('la fuente SEC enlaza al filing y una URL no http no se enlaza', () => {
        render(<ExpertThesisPanel thesis={thesis} t={createTranslator('es')} />);
        const sec = screen.getByRole('link', { name: /\[1\] Estados financieros · SEC EDGAR/ });
        expect(sec).toHaveAttribute('href', 'https://www.sec.gov/Archives/edgar/data/789019/x-index.htm');
        expect(sec).toHaveAttribute('rel', 'noopener noreferrer');
        expect(screen.queryByRole('link', { name: /\[2\] Estados/ })).toBeNull();
        expect(screen.getByText(/\[2\] Estados financieros · FY · 2024/)).toBeInTheDocument();
    });

    it('en inglés', () => {
        render(<ExpertThesisPanel thesis={thesis} t={createTranslator('en')} />);
        expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Expert team thesis');
        expect(screen.getByTestId('expert-thesis-fundamental')).toHaveTextContent('Fundamentals');
        expect(screen.getByTestId('expert-thesis-valuation')).toHaveTextContent('Did not answer in time.');
        expect(screen.getByText('Sources')).toBeInTheDocument();
    });

    it('sin tesis (flag apagado o ninguna guardada) no pinta nada', () => {
        const { container } = render(<ExpertThesisPanel thesis={null} t={createTranslator('es')} />);
        expect(container).toBeEmptyDOMElement();
    });
});
