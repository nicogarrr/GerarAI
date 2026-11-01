import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children, className }: { children: React.ReactNode; className?: string }) => <form className={className}>{children}</form> }));
vi.mock('@/lib/actions/research-tools.actions', () => ({
  createManagementPromiseResult: vi.fn(), importManagementCallClaims: vi.fn(), reconcileManagementCredibility: vi.fn(), updateManagementExplanationResult: vi.fn(),
  createDriverAssumptionResult: vi.fn(), decideDecisionLesson: vi.fn(), proposeDecisionLessons: vi.fn(), updateDecisionLessonResult: vi.fn(),
  getManagementCredibility: vi.fn(), getDriverAssumptions: vi.fn(), getDecisionLessons: vi.fn(),
}));
import { DecisionLessonsSection, type DecisionLessons } from '@/components/research/sections/DecisionLessonsSection';
import { DriverAssumptionsSection, type DriverAssumptions } from '@/components/research/sections/DriverAssumptionsSection';
import { ManagementCredibilitySection, type ManagementCredibility } from '@/components/research/sections/ManagementCredibilitySection';

const SPANISH = /[áéíóúñ¿]|Lecci|Promesa|Escenario|Guardar|Aprobar|Registrar|Supuesto|Historial/;

const dashboard = {
  score: 0.75, grade: 'mixed', method: 'resolved promises: met=1, partial=0.5, missed=0',
  counts: { open: 1, met: 2, partial: 0, missed: 1 },
  promises: [{ id: 1, status: 'missed', promise_date: '2026-03-01', expected_period: 'FY2026', promise: 'Margin above 30%', metric: null, operator: null, target_value: null, unit: null, actual_value: null, management_explanation: null }],
} as unknown as ManagementCredibility;
const assumptions = [{ id: 7, driver_key: 'revenue_growth', fiscal_year: 2027, scenario: 'bull', value: 1234.5, source: 'analyst', confidence: 0.8, rationale: 'r', previous_version_id: null, created_at: '2026-10-01T00:00:00Z' }] as unknown as DriverAssumptions;
const lessons = { taxonomy: ['timing'], lessons: [
  { id: 3, status: 'proposed', taxonomy: 'timing', decision_journal_entry_id: null, expectation_review_id: 4, expectation: 'e', outcome: 'o', deviation: 'd', cause: '', error: '', lesson: '', future_application: '' },
] } as unknown as DecisionLessons;

describe('secciones de la ficha en inglés', () => {
  it('credibilidad de la directiva', () => {
    const html = renderToStaticMarkup(<ManagementCredibilitySection dashboard={dashboard} locale="en" ticker="AAPL" />);
    expect(html).toContain('Record a promise');
    expect(html).toContain('missed');
    expect(html).toContain('mixed');
    expect(html).toContain('actual pending');
    expect(html).toContain('Method: resolved promises: met = 1, partial = 0.5, missed = 0.');
    expect(html.replace(/Margin above 30%/, '')).not.toMatch(SPANISH);
    const es = renderToStaticMarkup(<ManagementCredibilitySection dashboard={dashboard} ticker="AAPL" />);
    expect(es).toContain('Registrar una promesa');
    expect(es).toContain('real pendiente');
    expect(es).toContain('promesas resueltas: cumplida = 1, parcial = 0,5, fallida = 0');
  });

  it('supuestos de drivers', () => {
    const html = renderToStaticMarkup(<DriverAssumptionsSection assumptions={assumptions} locale="en" ticker="AAPL" />);
    expect(html).toContain('New assumption version');
    expect(html).toContain('Version history (1)');
    expect(html).toContain('1,234.5');
    expect(html).toContain('>bull<');
    expect(html).not.toMatch(SPANISH);
    expect(renderToStaticMarkup(<DriverAssumptionsSection assumptions={assumptions} ticker="AAPL" />)).toContain('alcista');
  });

  it('lecciones de decisiones', () => {
    const html = renderToStaticMarkup(<DecisionLessonsSection data={lessons} locale="en" ticker="AAPL" />);
    expect(html).toContain('Lesson #3 · decision #not linked · review #4');
    expect(html).toContain('Propose from deviations');
    expect(html).toContain('Approve');
    expect(html).not.toMatch(SPANISH);
    expect(renderToStaticMarkup(<DecisionLessonsSection data={lessons} ticker="AAPL" />)).toContain('Lección #3 · decisión #sin vínculo · revisión #4');
  });
});
