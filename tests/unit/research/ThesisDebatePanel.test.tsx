import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ThesisDebateResult } from '@/lib/actions/thesis-jobs.actions';
const mocks = vi.hoisted(() => ({ run: vi.fn() }));
vi.mock('@/lib/actions/thesis-jobs.actions', () => ({ runThesisDebate: mocks.run }));
import ThesisDebatePanel from '@/components/research/ThesisDebatePanel';
const outcome = (over: Partial<ThesisDebateResult> = {}) => ({ ok: true, debate: {
    ticker: 'TEST', bull_case: 'Caso alcista sintético', bear_case: 'Caso bajista sintético', verdict: 'bullish',
    verdict_rationale: 'Razón sintética', degraded: false, llm_calls: 2, model: 'fixture', persisted: true, ...over,
} });
beforeEach(() => vi.clearAllMocks());

describe('Thesis bull bear panel with mocked generation', () => {
    it('does not generate on mount and explains missing persisted debate', () => {
        render(<ThesisDebatePanel ticker="TEST" />);
        expect(screen.getByText(/Sin debate persistido/)).toBeVisible(); expect(mocks.run).not.toHaveBeenCalled();
        expect(screen.queryByText('juez LLM')).not.toBeInTheDocument();
    });
    it('preserves an initial verdict until a new result and blocks duplicate runs', async () => {
        let finish!: (result: ReturnType<typeof outcome>) => void;
        mocks.run.mockReturnValue(new Promise(resolve => { finish = resolve; }));
        render(<ThesisDebatePanel ticker="TEST" initialVerdict="Veredicto previo local" />);
        fireEvent.click(screen.getByRole('button'));
        expect(screen.getByText('Veredicto previo local')).toBeVisible();
        const busy = screen.getByRole('button', { name: 'Debatiendo…' });
        expect(busy).toBeDisabled(); expect(busy).toHaveAttribute('aria-busy', 'true');
        fireEvent.click(busy); expect(mocks.run).toHaveBeenCalledOnce(); expect(mocks.run).toHaveBeenCalledWith('TEST');
        await act(async () => finish(outcome()));
        expect(screen.queryByText('Veredicto previo local')).not.toBeInTheDocument();
        expect(screen.getByText('juez LLM')).toBeVisible();
        expect(screen.getByText('2 llamadas LLM · modelo fixture')).toBeVisible();
        expect(screen.getByText('Caso alcista sintético')).toBeVisible();
        expect(screen.getByText('Caso bajista sintético')).toBeVisible();
        expect(screen.getByText('veredicto: bullish')).toBeVisible();
        expect(screen.getByText('Razón sintética')).toBeVisible();
        expect(screen.getByRole('button', { name: 'Reintentar debate' })).toBeEnabled();
    });
    it('labels degraded fallback and nonpersisted verdict without inventing missing arguments', async () => {
        mocks.run.mockResolvedValue(outcome({ degraded: true, model: null, llm_calls: 0, persisted: false, verdict: 'bearish', bull_case: '', bear_case: '' }));
        render(<ThesisDebatePanel ticker="TEST" />); fireEvent.click(screen.getByRole('button'));
        expect(await screen.findByText('degradado · veredicto determinista')).toBeVisible();
        expect(screen.getByText('0 llamadas LLM · modelo determinista')).toBeVisible();
        expect(screen.getByText('Sin caso alcista registrado.')).toBeVisible();
        expect(screen.getByText('Sin caso bajista registrado.')).toBeVisible();
        expect(screen.getByText('veredicto no persistido (se muestra igual)')).toBeVisible();
        expect(screen.getByText('veredicto: bearish')).toBeVisible();
    });
    it.each(['returned', 'error', 'unknown'])('shows %s failure and recovers with an explicit retry', async mode => {
        if (mode === 'returned') mocks.run.mockResolvedValueOnce({ ok: false, error: 'Fuera de servicio' });
        else mocks.run.mockRejectedValueOnce(mode === 'error' ? new Error('Fuera de servicio') : 'offline');
        mocks.run.mockResolvedValueOnce(outcome());
        render(<ThesisDebatePanel ticker="TEST" />); fireEvent.click(screen.getByRole('button'));
        expect(await screen.findByRole('alert')).toHaveTextContent(mode === 'unknown' ? 'No se pudo generar el debate' : 'Fuera de servicio');
        expect(screen.getByRole('button', { name: 'Generar debate bull/bear' })).toBeEnabled();
        fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        expect(await screen.findByText('juez LLM')).toBeVisible();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(mocks.run).toHaveBeenCalledTimes(2);
    });
});
