import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatIntentLinks } from '@/components/research/ChatIntentLinks';
import { markBrainReady, OPEN_BRAIN_PENDING_KEY } from '@/lib/brain/open-brain';
afterEach(() => { markBrainReady(false); sessionStorage.clear(); vi.restoreAllMocks(); });
const intents = [
    ['Entender', '¿Qué hace BRK.B, cómo gana dinero y qué hechos y cálculos hay registrados sobre la empresa?'],
    ['Revisar supuestos', '¿Qué supuestos e hipótesis sostienen la tesis de BRK.B y qué evidencia tiene cada uno?'],
    ['Cuestionar', '¿Qué contradicciones, datos insuficientes y evidencia en contra hay registrados sobre BRK.B?'],
];
describe('Company research intent handoff', () => {
    it('does not open or enqueue anything before a click', () => {
        const listener = vi.fn(); window.addEventListener('gerarai:open-brain', listener);
        try {
            render(<ChatIntentLinks ticker="BRK.B" />);
            expect(screen.getAllByRole('button')).toHaveLength(3);
            for (const button of screen.getAllByRole('button')) expect(button).toHaveAttribute('type', 'button');
            expect(listener).not.toHaveBeenCalled(); expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        } finally { window.removeEventListener('gerarai:open-brain', listener); }
    });
    it.each(intents)('dispatches the exact evidence-seeking %s question when the panel is ready', (label, question) => {
        markBrainReady(true); const listener = vi.fn(); window.addEventListener('gerarai:open-brain', listener);
        try {
            render(<ChatIntentLinks ticker="BRK.B" />); fireEvent.click(screen.getByRole('button', { name: label }));
            expect(listener).toHaveBeenCalledOnce();
            expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ ticker: 'BRK.B', question });
            expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        } finally { window.removeEventListener('gerarai:open-brain', listener); }
    });
    it('queues context before the panel is ready and replaces rather than mixes prior questions', () => {
        render(<ChatIntentLinks ticker="BRK.B" />);
        fireEvent.click(screen.getByRole('button', { name: 'Entender' }));
        expect(JSON.parse(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)!)).toEqual({ ticker: 'BRK.B', question: intents[0][1] });
        fireEvent.click(screen.getByRole('button', { name: 'Cuestionar' }));
        expect(JSON.parse(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)!)).toEqual({ ticker: 'BRK.B', question: intents[2][1] });
    });
    it('does not crash if browser storage is unavailable', () => {
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
        render(<ChatIntentLinks ticker="BRK.B" />);
        expect(() => fireEvent.click(screen.getByRole('button', { name: 'Entender' }))).not.toThrow();
    });
});
