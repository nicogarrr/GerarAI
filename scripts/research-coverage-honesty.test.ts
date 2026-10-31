import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error Node strip-types requires the explicit TS extension.
import { researchValuability, modelConditionState, visibleThesisRating } from '../lib/research/coverage-state.ts';
const complete = { latest_thesis: { status: 'ok' }, model_summary: { status: 'ok', publishable: true }, valuation_summary: { status: 'ok' } };
test('coverage never makes insufficient thesis or blocked model valueable', () => {
  assert.equal(researchValuability({ ...complete, latest_thesis: { status: 'insufficient_data' } }), 'No valorable / falta evidencia');
  assert.equal(researchValuability({ ...complete, model_summary: { status: 'blocked', publishable: false } }), 'No valorable / falta evidencia');
  assert.equal(researchValuability({ ...complete, model_summary: null }), 'No valorable / falta evidencia');
  assert.equal(researchValuability(complete), 'Revisar tesis y supuestos');
});
test('conditions are pending, not fulfilled just because they exist', () => {
  assert.equal(modelConditionState({ id: 'roic_above_wacc', value: .1, comparison: .08, status: 'monitor' }, false), 'Pendiente: WACC sin datos');
  assert.equal(modelConditionState({ id: 'fcf_margin', value: -15.461, status: 'monitor' }, true), 'No cumplida: margen FCF fuera de rango');
  assert.equal(modelConditionState({ id: 'revenue_growth', value: .1, status: 'monitor' }, true), 'Pendiente de contrastar');
  assert.equal(modelConditionState({ id: 'revenue_growth', value: null, status: 'monitor' }, true), 'Pendiente: falta evidencia');
});
test('index and overview use coverage and a separate evidence state', () => {
  for (const file of ['app/(root)/research/page.tsx', 'app/(root)/research/[ticker]/page.tsx']) {
    const source = readFileSync(file, 'utf8');
    // La ficha ya no pinta tarjetas de cobertura (Nico 2026-10-19); el indice si.
    if (file === 'app/(root)/research/page.tsx') {
      assert.match(source, /t\('research\.layersAvailable'/);
      assert.match(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).layersAvailable, /^Capas disponibles \{score\}\/100$/);
    }
    assert.match(source, /researchValuability\(snapshot\)/);
    assert.doesNotMatch(source, /Salud del research|Salud \{/);
  }
  const panel = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
  assert.doesNotMatch(panel, /CheckCircle2/);
  assert.match(panel, /modelConditionState\(item/);
});

test('un veredicto de valoración no contradice el estado no valorable (caso ADBE)', () => {
  const blocked = { ...complete, model_summary: { status: 'blocked', publishable: false } };
  assert.equal(visibleThesisRating('attractive', blocked), null);
  assert.equal(visibleThesisRating('expensive', blocked), null);
  assert.equal(visibleThesisRating('attractive', complete), 'attractive');
  assert.equal(visibleThesisRating('insufficient_data', blocked), 'insufficient_data');
});
