// Preflight behavior is covered in ai/AiAvailabilityNotice.test.tsx.
vi.mock('@/components/ai/AiAvailabilityNotice', () => ({
    useAiAvailability: () => ({ canStart: true, refresh: async () => true }),
    AiAvailabilityNotice: () => null,
}));
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ run: vi.fn() }));
vi.mock('@/lib/actions/thesis-jobs.actions', () => ({ runThesisDebate: mocks.run }));
import ThesisDebatePanel from '@/components/research/ThesisDebatePanel';
import { LocaleProvider } from '@/lib/i18n/client';
import { debateVerdict, parsePersistedVerdict } from '@/lib/research/debate-verdict';

// El juez emite «bullish/bearish/neutral» (prompt sin cambios) y la sección
// persistida guarda «VEREDICTO: <palabra> | <frase>» (routes/thesis.py). En
// castellano se veía «veredicto: bullish» y el cuerpo crudo con «VEREDICTO:».
const debate = (verdict: string) => ({ ok: true, debate: {
    ticker: 'TEST', bull_case: 'A favor', bear_case: 'En contra', verdict,
    verdict_rationale: 'Razón', degraded: false, llm_calls: 3, model: 'fixture', persisted: true,
} });
beforeEach(() => vi.clearAllMocks());

describe('debate verdict shown in the user language', () => {
    it.each([['bullish', 'veredicto: alcista'], ['bearish', 'veredicto: bajista'], ['neutral', 'veredicto: neutral']])(
        'Spanish: %s', async (verdict, shown) => {
            mocks.run.mockResolvedValue(debate(verdict));
            render(<ThesisDebatePanel ticker="TEST" />); fireEvent.click(screen.getByRole('button'));
            expect(await screen.findByText(shown)).toBeVisible();
        });
    it('English keeps the judge word', async () => {
        mocks.run.mockResolvedValue(debate('bearish'));
        render(<LocaleProvider locale="en"><ThesisDebatePanel ticker="TEST" /></LocaleProvider>);
        fireEvent.click(screen.getByRole('button'));
        expect(await screen.findByText('verdict: bearish')).toBeVisible();
    });
    it('an unknown word is shown as is', async () => {
        mocks.run.mockResolvedValue(debate('mixed'));
        render(<ThesisDebatePanel ticker="TEST" />); fireEvent.click(screen.getByRole('button'));
        expect(await screen.findByText('veredicto: mixed')).toBeVisible();
    });
    it('persisted section body is read, not shown raw', () => {
        render(<ThesisDebatePanel ticker="TEST" initialVerdict="VEREDICTO: bullish | Los márgenes mejoran." />);
        expect(screen.getByText('veredicto: alcista · Los márgenes mejoran.')).toBeVisible();
        expect(screen.queryByText(/VEREDICTO:/)).not.toBeInTheDocument();
    });
    it('persisted section body in English', () => {
        render(<LocaleProvider locale="en"><ThesisDebatePanel ticker="TEST" initialVerdict="VEREDICTO: neutral | Mixed signals." /></LocaleProvider>);
        expect(screen.getByText('verdict: neutral · Mixed signals.')).toBeVisible();
    });
    it('parses only the persisted format', () => {
        expect(parsePersistedVerdict('VEREDICTO: Bearish')).toEqual({ verdict: 'bearish', rationale: '' });
        expect(parsePersistedVerdict('Veredicto previo local')).toBeNull();
        expect(parsePersistedVerdict('VEREDICTO: quizás | algo')).toBeNull();
        expect(debateVerdict(' NEUTRAL ')).toBe('neutral');
        expect(debateVerdict(null)).toBeNull();
    });
});
