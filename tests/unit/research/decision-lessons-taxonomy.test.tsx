import React from 'react';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children, className }: { children: React.ReactNode; className?: string }) => <form className={className}>{children}</form> }));
vi.mock('@/lib/actions/research-tools.actions', () => ({
  decideDecisionLesson: vi.fn(), proposeDecisionLessons: vi.fn(), updateDecisionLessonResult: vi.fn(), getDecisionLessons: vi.fn(),
}));
import { DecisionLessonsSection, type DecisionLessons } from '@/components/research/sections/DecisionLessonsSection';

// Taxonomía REAL de errores de decisión (decision_learning_service.DECISION_ERROR_TAXONOMY, leída del .py);
// /companies/{ticker}/decision-lessons la devuelve ordenada y cada lección guarda una de estas claves.
const PY = readFileSync('data-engine/app/services/decision_learning_service.py', 'utf8');
const BLOCK = /DECISION_ERROR_TAXONOMY = \{([^}]+)\}/.exec(PY)?.[1] ?? '';
const TAXONOMY = [...BLOCK.matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort();

const data = (taxonomy: string, status = 'proposed') => ({ taxonomy: TAXONOMY, lessons: [
  { id: 3, status, taxonomy, decision_journal_entry_id: null, expectation_review_id: 4, expectation: 'e', outcome: 'o', deviation: 'd', cause: 'c', error: taxonomy, lesson: 'l', future_application: 'f' },
] }) as unknown as DecisionLessons;

describe('lecciones de decisión: tipo de error legible', () => {
  it('la taxonomía de prueba es la del backend', () => {
    expect(TAXONOMY).toHaveLength(10);
    expect(TAXONOMY).toContain('underestimating_dilution');
  });
  it.each(['es', 'en'] as const)('ninguna clave cruda en la etiqueta ni en el desplegable (%s)', (locale) => {
    for (const key of TAXONOMY) {
      const html = renderToStaticMarkup(<DecisionLessonsSection data={data(key)} locale={locale} ticker="AAPL" />);
      // La clave sigue siendo el valor enviado al guardar…
      expect(html).toContain(`value="${key}"`);
      // …pero el texto visible ya no es la clave cruda ni «underestimating dilution».
      // (el campo «error» editable sí trae la clave tal cual del backend, como texto del analista).
      for (const tag of ['div', 'option']) {
        expect(html).not.toContain(`>${key}</${tag}>`);
        expect(html).not.toContain(`>${key.replaceAll('_', ' ')}</${tag}>`);
      }
    }
  });
  it('en castellano y en inglés', () => {
    const es = renderToStaticMarkup(<DecisionLessonsSection data={data('underestimating_dilution', 'approved')} ticker="AAPL" />);
    expect(es).toContain('Infravalorar la dilución');
    const en = renderToStaticMarkup(<DecisionLessonsSection data={data('underestimating_dilution', 'approved')} locale="en" ticker="AAPL" />);
    expect(en).toContain('Underestimating dilution');
  });
});
