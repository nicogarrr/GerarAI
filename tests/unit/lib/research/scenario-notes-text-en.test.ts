import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { scenarioNoteText } from '@/lib/research/scenario-notes-text';

// Notas N/D tal cual las escriben los motores (salida real de
// base.scenario_value_or_nd / expected_value_or_nd y standard_dcf._scenario_nd_note).
const NOTES = [
  "Escenario bajista: el modelo no produjo un valor por acción calculable: N/D.",
  "Escenario alcista: Con los supuestos de este escenario el valor por acción sale -3,46. Una cifra negativa no es una valoración publicable: N/D. El valor esperado sí la tiene en cuenta.",
  "El valor esperado (ponderado por probabilidad) sale -12,00 con estos supuestos: N/D, no se publica una cifra negativa.",
  "Escenario bajista: el modelo no produjo un valor por acción calculable: N/D.",
  "Escenario base: con el margen FCF de este escenario (-2,34 %) la empresa quema más caja de la que genera y el valor por acción sale -1,50. Una cifra negativa no es una valoración publicable: N/D. El valor esperado sí la tiene en cuenta.",
  "Escenario alcista: la deuda y las obligaciones superan el valor del negocio en este escenario y el valor por acción sale -20,25. Una cifra negativa no es una valoración publicable: N/D. El valor esperado sí la tiene en cuenta."
];
const join = (path: string) => readFileSync(path, 'utf8').replace(/"\s*\n\s*f?"/g, '');
const SPANISH = /\b(Escenario|bajista|alcista|valor|sale|cifra|supuestos|empresa|deuda|esperado|N\/D)\b/;

describe('notas N/D de escenarios de valoración en inglés', () => {
  it('los motores siguen escribiendo estas frases', () => {
    const base = join('data-engine/app/valuation/engines/base.py');
    const dcf = join('data-engine/app/valuation/engines/standard_dcf.py');
    expect(base).toContain('_SCENARIO_LABEL_ES = {"bear": "bajista", "base": "base", "bull": "alcista"}');
    expect(base).toContain('f"Escenario {label}: el modelo no produjo un valor por acción calculable: N/D."');
    expect(base).toContain('detail = f" {cause}" if cause else " Con los supuestos de este escenario"');
    expect(base).toContain('f"Escenario {label}:{detail} el valor por acción sale {num_es(value)}. Una cifra negativa no es una valoración publicable: N/D. El valor esperado sí la tiene en cuenta."');
    expect(base).toContain('"El valor esperado (ponderado por probabilidad) sale f"{num_es(expected_raw)} con estos supuestos: N/D, no se publica una cifra negativa."'.replace('sale f"', 'sale '));
    expect(dcf).toContain('f"Escenario {label}: con el margen FCF de este escenario ({_pct_es(scenario_margin)}) la empresa quema más caja de la que genera y el valor por acción sale {_num_es(raw_value)}. Una cifra negativa no es una valoración publicable: N/D. El valor esperado sí la tiene en cuenta."');
    expect(dcf).toContain('f"Escenario {label}: la deuda y las obligaciones superan el valor del negocio en este escenario y el valor por acción sale {_num_es(raw_value)}. Una cifra negativa no es una valoración publicable: N/D. El valor esperado sí la tiene en cuenta."');
  });

  it('cada nota real sale en inglés, con la cifra en formato inglés', () => {
    for (const note of NOTES) {
      const en = scenarioNoteText(note, 'en');
      expect(en, note).not.toBe(note);
      expect(en, note).not.toMatch(SPANISH);
      expect(en, note).not.toMatch(/\d,\d/);
    }
    expect(scenarioNoteText(NOTES[4], 'en')).toBe(
      "Base scenario: with this scenario's FCF margin (-2.34%) the company burns more cash than it generates and the value per share comes out at -1.50. A negative figure is not a publishable valuation: N/A. The expected value does take it into account.",
    );
    expect(scenarioNoteText(NOTES[2], 'en')).toBe('The expected (probability-weighted) value comes out at -12.00 with these assumptions: N/A, a negative figure is not published.');
    expect(scenarioNoteText(NOTES[0], 'en')).toBe('Bear scenario: the model did not produce a computable value per share: N/A.');
  });

  it('en castellano, o con una nota desconocida, pasa tal cual', () => {
    for (const note of NOTES) expect(scenarioNoteText(note, 'es')).toBe(note);
    expect(scenarioNoteText('bear scenario revalued at base inputs: wacc.', 'en')).toBe('bear scenario revalued at base inputs: wacc.');
    expect(scenarioNoteText('Escenario raro: el modelo no produjo un valor por acción calculable: N/D.', 'en')).toBe('Escenario raro: el modelo no produjo un valor por acción calculable: N/D.');
  });

  it('la ficha pinta las notas con el idioma', () => {
    const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    expect(page.split('scenarioNoteText(note, locale)').length - 1).toBe(2);
  });
});
