import { describe, expect, it } from 'vitest';
import { debateErrorMessage } from '@/lib/research/debate-error';

describe('debateErrorMessage en inglés', () => {
    it('traduce solo los motivos públicos fijos y el genérico', () => {
        expect(debateErrorMessage(new Error('Presupuesto LLM agotado, vuelve más tarde'), 'en')).toBe('The AI budget is used up; try again later');
        expect(debateErrorMessage(new Error('LLM gratuito agotado, vuelve más tarde'), 'en')).toBe('The free AI quota is used up; try again later');
        expect(debateErrorMessage(Object.assign(new Error('x'), { name: 'TimeoutError' }), 'en')).toBe('The debate took too long; try again later');
        expect(debateErrorMessage(new Error('https://provider.example/secret'), 'en')).toBe("The debate couldn't be generated; try again.");
        expect(debateErrorMessage('boom', 'en')).toBe("The debate couldn't be generated; try again.");
    });
    it('en español devuelve el mismo texto que antes', () => {
        expect(debateErrorMessage(new Error('Presupuesto LLM agotado, vuelve más tarde'))).toBe('Presupuesto LLM agotado, vuelve más tarde');
        expect(debateErrorMessage(new Error('otra cosa'))).toBe('No se pudo generar el debate; reinténtalo.');
    });
});
