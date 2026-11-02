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
    is_latest: true,
    judge_timed_out: false,
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

    it('las fuentes de valoración y cartera enlazan a su pantalla de la app; riesgo sin enlace', () => {
        const internal: ExpertThesis = {
            ...thesis,
            sources: [
                { n: 1, title: 'Motor de valoración · 2026-10-30', url: '/research/MSFT?view=valoracion' },
                { n: 2, title: 'Cartera · 2026-11-01', url: '/portfolio' },
                { n: 3, title: 'Alertas de riesgo · 2026-10-31', url: null },
                { n: 4, title: 'Redirección', url: '//evil.example/x' },
            ],
        };
        render(<ExpertThesisPanel thesis={internal} t={createTranslator('es')} />);
        const valuation = screen.getByRole('link', { name: /\[1\] Motor de valoración/ });
        expect(valuation).toHaveAttribute('href', '/research/MSFT?view=valoracion');
        expect(valuation).not.toHaveAttribute('target');
        expect(screen.getByRole('link', { name: /\[2\] Cartera/ })).toHaveAttribute('href', '/portfolio');
        expect(screen.queryByRole('link', { name: /\[3\] Alertas de riesgo/ })).toBeNull();
        expect(screen.queryByRole('link', { name: /\[4\] Redirección/ })).toBeNull();
    });

    it('en inglés', () => {
        render(<ExpertThesisPanel thesis={thesis} t={createTranslator('en')} />);
        expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Expert team thesis');
        expect(screen.getByTestId('expert-thesis-fundamental')).toHaveTextContent('Fundamentals');
        expect(screen.getByTestId('expert-thesis-valuation')).toHaveTextContent('Did not answer in time.');
        expect(screen.getByText('Sources')).toBeInTheDocument();
    });

    it('historial corto de corridas anteriores, la más reciente primero', () => {
        const withHistory: ExpertThesis = {
            ...thesis,
            history: [
                { run_id: 5, finished_at: '2026-10-31T09:00:00Z', verdict: 'neutral', answered: ['fundamental', 'valuation'], timed_out: ['risk'], judge_timed_out: false },
                { run_id: 3, finished_at: '2026-10-20T09:00:00Z', verdict: null, answered: ['fundamental'], timed_out: [], judge_timed_out: false },
            ],
        };
        render(<ExpertThesisPanel thesis={withHistory} t={createTranslator('es')} formatDate={(iso) => iso.slice(0, 10)} />);
        const history = screen.getByTestId('expert-thesis-history');
        expect(history).toHaveTextContent('Corridas anteriores');
        const items = within(history).getAllByRole('listitem');
        expect(items.map((li) => li.getAttribute('data-testid'))).toEqual(['expert-thesis-run-5', 'expert-thesis-run-3']);
        expect(items[0]).toHaveTextContent('2026-10-31');
        expect(items[0]).toHaveTextContent('Veredicto: neutral');
        expect(items[0]).toHaveTextContent('Respondieron: Fundamental · Valoración');
        expect(items[0]).toHaveTextContent('Sin respuesta a tiempo: Riesgo');
        expect(items[1]).toHaveTextContent('Sin veredicto');
        expect(items[1]).not.toHaveTextContent('Sin respuesta a tiempo');
    });

    it('historial en inglés y oculto si no hay corridas anteriores', () => {
        const withHistory: ExpertThesis = {
            ...thesis,
            history: [{ run_id: 5, finished_at: '2026-10-31T09:00:00Z', verdict: 'positive', answered: ['news'], timed_out: ['tax'], judge_timed_out: false }],
        };
        const { unmount } = render(<ExpertThesisPanel thesis={withHistory} t={createTranslator('en')} />);
        const history = screen.getByTestId('expert-thesis-history');
        expect(history).toHaveTextContent('Earlier runs');
        expect(history).toHaveTextContent('2026-10-31');
        expect(history).toHaveTextContent('Verdict: positive');
        expect(history).toHaveTextContent('Answered: News');
        expect(history).toHaveTextContent('Did not answer in time: Tax');
        unmount();
        render(<ExpertThesisPanel thesis={{ ...thesis, history: [] }} t={createTranslator('es')} />);
        expect(screen.queryByTestId('expert-thesis-history')).toBeNull();
    });

    it('cada corrida anterior se abre entera con ?expertRun= (solo con basePath)', () => {
        const withHistory: ExpertThesis = {
            ...thesis,
            history: [{ run_id: 5, finished_at: '2026-10-31T09:00:00Z', verdict: 'neutral', answered: ['fundamental'], timed_out: [], judge_timed_out: false }],
        };
        const { unmount } = render(
            <ExpertThesisPanel thesis={withHistory} t={createTranslator('es')} basePath="/research/MSFT/tesis" formatDate={(iso) => iso.slice(0, 10)} />,
        );
        const link = within(screen.getByTestId('expert-thesis-run-5')).getByRole('link', { name: '2026-10-31' });
        expect(link).toHaveAttribute('href', '/research/MSFT/tesis?expertRun=5#expert-thesis');
        expect(screen.queryByTestId('expert-thesis-older')).toBeNull();
        unmount();
        render(<ExpertThesisPanel thesis={withHistory} t={createTranslator('es')} />);
        expect(within(screen.getByTestId('expert-thesis-run-5')).queryByRole('link')).toBeNull();
    });

    it('una corrida anterior abierta lo avisa y deja volver a la última', () => {
        const older: ExpertThesis = { ...thesis, is_latest: false, history: [] };
        const { unmount } = render(
            <ExpertThesisPanel thesis={older} t={createTranslator('es')} basePath="/research/MSFT/tesis" formatDate={(iso) => iso.slice(0, 10)} />,
        );
        const note = screen.getByTestId('expert-thesis-older');
        expect(note).toHaveTextContent('Estás viendo una corrida anterior (2026-11-01).');
        expect(within(note).getByRole('link', { name: 'Ver la última' })).toHaveAttribute('href', '/research/MSFT/tesis#expert-thesis');
        unmount();
        render(<ExpertThesisPanel thesis={older} t={createTranslator('en')} basePath="/research/MSFT/tesis" />);
        expect(screen.getByTestId('expert-thesis-older')).toHaveTextContent('You are viewing an earlier run');
        expect(screen.getByRole('link', { name: 'See the latest' })).toBeInTheDocument();
    });

    it('si el juez no llegó a tiempo lo dice, en la tesis y en el historial', () => {
        const slowJudge: ExpertThesis = {
            ...thesis,
            verdict: null,
            judge_timed_out: true,
            history: [
                { run_id: 5, finished_at: '2026-10-31T09:00:00Z', verdict: null, answered: ['fundamental'], timed_out: [], judge_timed_out: true },
                { run_id: 3, finished_at: '2026-10-20T09:00:00Z', verdict: null, answered: ['fundamental'], timed_out: [], judge_timed_out: false },
            ],
        };
        const { unmount } = render(<ExpertThesisPanel thesis={slowJudge} t={createTranslator('es')} formatDate={(iso) => iso.slice(0, 10)} />);
        expect(screen.queryByTestId('expert-thesis-verdict')).toBeNull();
        expect(screen.getByTestId('expert-thesis-judge-timeout')).toHaveTextContent(
            'El juez no llegó a tiempo: sin veredicto, quedan las posturas de cada experto.',
        );
        expect(screen.getByTestId('expert-thesis-run-5')).toHaveTextContent('El juez no llegó a tiempo');
        expect(screen.getByTestId('expert-thesis-run-5')).not.toHaveTextContent('Sin veredicto');
        expect(screen.getByTestId('expert-thesis-run-3')).toHaveTextContent('Sin veredicto');
        unmount();
        render(<ExpertThesisPanel thesis={slowJudge} t={createTranslator('en')} formatDate={(iso) => iso.slice(0, 10)} />);
        expect(screen.getByTestId('expert-thesis-judge-timeout')).toHaveTextContent('The judge did not answer in time');
        expect(screen.getByTestId('expert-thesis-run-5')).toHaveTextContent('Judge out of time');
    });

    it('con veredicto o sin choque no sale el aviso del juez', () => {
        render(<ExpertThesisPanel thesis={thesis} t={createTranslator('es')} />);
        expect(screen.queryByTestId('expert-thesis-judge-timeout')).toBeNull();
    });

    it('sin tesis (flag apagado o ninguna guardada) no pinta nada', () => {
        const { container } = render(<ExpertThesisPanel thesis={null} t={createTranslator('es')} />);
        expect(container).toBeEmptyDOMElement();
    });
});
