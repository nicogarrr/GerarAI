/**
 * Guard: el aviso del motor de valoración (trace.notice) llega a la ficha en
 * el idioma de la UI, y las métricas del puente de equity tienen etiqueta.
 *
 * Los motores guardan la traza técnica en inglés (valuation/engines/base.py,
 * pre_revenue.py); el memo la traduce en thesis_service._notice_es pero la
 * ficha interpolaba el literal crudo bajo una etiqueta en español («Nota del
 * motor: INDICATIVE RANGE — ...»). Y metricLabel mostraba «minority
 * interest» / «preferred stock» crudos: son claves del puente de equity del
 * backend (thesis_service.py) sin entrada en las tablas del front.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/engine-notice-es-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { engineNoticeText } from '../lib/research/engine-notice.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS } from '../lib/research/metric-labels.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS_EN } from '../lib/research/metric-labels-en.ts';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

describe('engineNoticeText traduce los avisos técnicos del motor en UI ES', () => {
  it('INDICATIVE RANGE sale en español (mismo texto que thesis_service._notice_es)', () => {
    assert.equal(
      engineNoticeText('INDICATIVE RANGE — uses assumed FCF margin (base 15%)', 'es'),
      'RANGO INDICATIVO: usa un margen FCF supuesto porque no hay un balance coherente. No es un valor justo final; resuelve los inputs que faltan antes de publicar.',
    );
  });
  it('«Valuation computed…» sale en español', () => {
    assert.equal(
      engineNoticeText('Valuation computed on inputs that are not traceable to a dated source', 'es'),
      'Valoración calculada con inputs que no se pueden rastrear hasta una fuente fechada: las cifras son una orientación, no una valoración final.',
    );
  });
  it('en inglés pasa tal cual, y un aviso ya en español no se toca', () => {
    const en = 'INDICATIVE RANGE — uses assumed FCF margin (base 15%)';
    assert.equal(engineNoticeText(en, 'en'), en);
    const es = 'Valoración orientativa por múltiplos de comparables: el motor sectorial (retail) no tiene sus datos (net_debt).';
    assert.equal(engineNoticeText(es, 'es'), es);
  });
});

describe('la ficha no interpola trace.notice crudo', () => {
  it('page.tsx pasa el aviso por engineNoticeText', () => {
    assert.match(page, /engineNoticeText\(engineNotice/);
    assert.doesNotMatch(page, /\{ note: engineNotice \}/);
  });
});

describe('las claves del puente de equity del backend tienen etiqueta ES y EN', () => {
  for (const key of ['minority_interest', 'preferred_stock']) {
    it(`${key} tiene etiqueta en las dos tablas`, () => {
      assert.ok(METRIC_LABELS[key], `falta ${key} en METRIC_LABELS (es)`);
      assert.ok(METRIC_LABELS_EN[key], `falta ${key} en METRIC_LABELS_EN (en)`);
      assert.ok(!/minority|preferred/i.test(METRIC_LABELS[key]), 'la etiqueta ES no puede quedar en inglés');
    });
  }
});
