import { describe, expect, it } from 'vitest';
import { thesisProgressText, type ThesisProgressInput } from '@/lib/research/thesis-progress';

const job = (over: Partial<ThesisProgressInput> = {}): ThesisProgressInput => ({
    status: 'running', current_phase: 'compose_thesis', total_phases: 8, started_at: '2026-10-01T10:00:00Z',
    phases: [{ name: 'refresh_sec', status: 'done' }, { name: 'compose_thesis', status: 'running' }], ...over,
});
const t0 = Date.parse('2026-10-01T10:00:00Z');

describe('thesisProgressText', () => {
    it('sin trabajo, parado o sin fase actual: nada que mostrar', () => {
        expect(thesisProgressText(null, t0)).toBeNull();
        expect(thesisProgressText(job({ status: 'completed' }), t0)).toBeNull();
        expect(thesisProgressText(job({ current_phase: null }), t0)).toBeNull();
    });
    it('fase, posición, total y segundos transcurridos', () => {
        expect(thesisProgressText(job(), t0 + 12_400)).toBe('Fase 2 de 8: Redactando la tesis · 12 s');
    });
    it('fase desconocida: etiqueta genérica; posición = nº de fases si no está en la lista', () => {
        expect(thesisProgressText(job({ current_phase: 'nueva' }), t0)).toBe('Fase 2 de 8: Análisis en curso · 0 s');
    });
    it('total inválido (menor que la posición o ausente): sin "de N"', () => {
        expect(thesisProgressText(job({ total_phases: 1 }), t0)).toMatch(/^Fase 2: /);
        expect(thesisProgressText(job({ total_phases: null }), t0)).toMatch(/^Fase 2: /);
    });
    it('sin inicio válido, reloj en 0 o inicio en el futuro: no inventa segundos', () => {
        expect(thesisProgressText(job({ started_at: null }), t0)).toBe('Fase 2 de 8: Redactando la tesis');
        expect(thesisProgressText(job({ started_at: 'x' }), t0)).not.toContain(' s');
        expect(thesisProgressText(job(), 0)).not.toContain(' s');
        expect(thesisProgressText(job(), t0 - 5000)).not.toContain(' s');
    });
});
