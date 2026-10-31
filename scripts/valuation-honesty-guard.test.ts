import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// F89: una valoración no publicable (estado partial, entradas sin
// trazabilidad fechada) no puede renderizarse como precio objetivo limpio.
// El motivo va primero y los números degradados como orientación.

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');
const fichaEs = JSON.parse(source('lib/i18n/messages/es/research.json')).ficha;

void test('la vista de valoración separa notPublishable antes de pintar números', () => {
  const page = source('app/(root)/research/[ticker]/page.tsx');
  const view = page.slice(page.indexOf('function ValuationView'), page.indexOf('function MarketOpportunityView'));
  assert.ok(view.includes("valuation.status !== 'ok' || valuation.publishable === false"), 'debe detectar estado no publicable');
  assert.ok(view.includes('publication_blockers'), 'debe leer los bloqueos del trace');
  const warnAt = view.indexOf("t('research.ficha.engineGuidanceTitle')");
  assert.ok(fichaEs.engineGuidanceTitle.includes('no precio objetivo'), 'ES conserva el literal');
  const guardAt = view.indexOf('notPublishable');
  assert.ok(guardAt !== -1 && warnAt !== -1, 'aviso visible en la rama no publicable');
  assert.ok(view.includes("t('research.ficha.bearGuidance')") && view.includes("t('research.ficha.bullGuidance')"), 'los números se etiquetan como orientación');
  assert.ok(fichaEs.bearGuidance.includes('(orientación)') && fichaEs.bullGuidance.includes('(orientación)'), 'ES conserva el literal');
});

void test('sin blockers el panel NO afirma una causa por defecto', () => {
  const page = source('app/(root)/research/[ticker]/page.tsx');
  const view = page.slice(page.indexOf('function ValuationView'), page.indexOf('function MarketOpportunityView'));
  // La causa concreta (entradas sin trazabilidad, supuestos por defecto) solo
  // puede aparecer condicionada a que existan blockers/missing/notice.
  assert.ok(!view.includes('le faltan entradas trazables a una fuente fechada'), 'causa por defecto prohibida');
  assert.ok(!view.includes('salida cruda del modelo con supuestos por defecto'), 'causa por defecto prohibida');
  assert.ok(view.includes("t('research.ficha.blockers'"), 'los motivos se muestran cuando existen');
  assert.ok(fichaEs.blockers.startsWith('Motivos registrados:'), 'ES conserva el literal');
  assert.ok(view.includes('engineNotice'), 'la nota del motor se muestra cuando existe');
});

void test('los números de orientación van degradados (opacity), no como tarjetas limpias', () => {
  const page = source('app/(root)/research/[ticker]/page.tsx');
  const view = page.slice(page.indexOf('function ValuationView'), page.indexOf('function MarketOpportunityView'));
  const branch = view.slice(view.indexOf('if (notPublishable)'), view.indexOf('return (\n    <div className="space-y-3">\n      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">'));
  assert.ok(branch.includes('opacity-60'), 'rama no publicable degrada los números');
  assert.ok(!branch.includes('>Bear<'), 'sin tarjetas de objetivo limpias en la rama no publicable');
});
