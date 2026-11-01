import { describe, expect, it } from 'vitest';
import { thesisPhaseLabel, thesisProgressText } from '@/lib/research/thesis-progress';

describe('thesis progress in English', () => {
  const job = { status: 'running', current_phase: 'compose_thesis', total_phases: 8, started_at: '2026-10-27T11:00:00Z',
    phases: [{ name: 'refresh_sec', status: 'done' }, { name: 'compose_thesis', status: 'running' }] };
  it('phase label and progress line', () => {
    expect(thesisProgressText(job, Date.parse('2026-10-27T11:00:12Z'), 'en')).toBe('Phase 2 of 8: Writing the thesis · 12 s');
    expect(thesisPhaseLabel('nueva_fase', 'en')).toBe('Analysis in progress');
  });
  it('Spanish unchanged', () => {
    expect(thesisProgressText(job, Date.parse('2026-10-27T11:00:12Z'))).toBe('Fase 2 de 8: Redactando la tesis · 12 s');
  });
});
