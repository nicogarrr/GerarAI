// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { thesisProgressText, type ThesisProgressInput } from '@/lib/research/thesis-progress';

const job = (patch: Partial<ThesisProgressInput>): ThesisProgressInput => ({
    status: 'running',
    phases: [{ name: 'refresh_sec', status: 'done' }, { name: 'collect_evidence', status: 'running' }],
    current_phase: 'collect_evidence',
    total_phases: 8,
    started_at: '2026-10-27T10:00:00Z',
    ...patch,
});
const NOW = Date.parse('2026-10-27T10:00:45Z');

describe('thesisProgressText', () => {
    it('fase en curso con número, total y segundos reales del job', () => {
        expect(thesisProgressText(job({}), NOW)).toBe('Fase 2 de 8: Recopilando evidencia (SEC, noticias, filings) · 45 s');
    });
    it('sin job, sin status running o sin fase en curso: null (el llamador pone su texto)', () => {
        expect(thesisProgressText(null, NOW)).toBeNull();
        expect(thesisProgressText(job({ status: 'queued' }), NOW)).toBeNull();
        expect(thesisProgressText(job({ current_phase: null }), NOW)).toBeNull();
    });
    it('fase desconocida: etiqueta genérica, nunca la clave cruda', () => {
        expect(thesisProgressText(job({ current_phase: 'fase_nueva_backend' }), NOW)).toContain('Análisis en curso');
    });
    it('sin total fiable omite «de N» (nunca inventa el total)', () => {
        expect(thesisProgressText(job({ total_phases: null }), NOW)).toContain('Fase 2: ');
        expect(thesisProgressText(job({ total_phases: 1 }), NOW)).toContain('Fase 2: '); // total < posición: no fiable
    });
    it('fase fuera de la lista usa la longitud como posición', () => {
        expect(thesisProgressText(job({ current_phase: 'compose_thesis', phases: [] }), NOW)).toContain('Fase 0 de 8: Redactando la tesis');
    });
    it('sin started_at válido no muestra segundos (nunca un ETA inventado)', () => {
        expect(thesisProgressText(job({ started_at: null }), NOW)).toBe('Fase 2 de 8: Recopilando evidencia (SEC, noticias, filings)');
        expect(thesisProgressText(job({ started_at: 'no-fecha' }), NOW)).not.toContain('· ');
        // Reloj hacia atrás: no muestra segundos negativos
        expect(thesisProgressText(job({ started_at: '2026-10-27T11:00:00Z' }), NOW)).not.toContain('·');
    });
});
