/**
 * Guard: las claves de señal del monitor insider no se muestran en crudo.
 *
 * Barrido Tester 6 (2026-10-19): los badges de la vista de señales pintaban
 * la clave del backend («cluster_buy», «c_suite_buy», «big_buy»). Contrato
 * de signalLabel: mapa FIJO clave -> etiqueta ES; clave nueva desconocida
 * se muestra cruda (honesta), nunca inventada. La lógica (signalTone) sigue
 * comparando la clave, no la etiqueta.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/insider-senales-es-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extension .ts explicita la exige node --experimental-strip-types en runtime
const { signalLabel } = await import('../lib/insider/format.ts');

const signalsView = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');

describe('Insider: claves de señal con etiqueta ES', () => {
  it('traduce las tres claves del monitor', () => {
    assert.equal(signalLabel('cluster_buy'), 'Cluster de compra');
    assert.equal(signalLabel('c_suite_buy'), 'Compra de alto directivo');
    assert.equal(signalLabel('big_buy'), 'Gran compra');
  });

  it('clave desconocida: cruda, nunca inventada; vacía: guion', () => {
    assert.equal(signalLabel('future_signal_x'), 'future_signal_x');
    assert.equal(signalLabel(''), '—');
    assert.equal(signalLabel(null), '—');
  });

  it('la vista pinta la etiqueta y no la clave cruda', () => {
    const usos = signalsView.match(/signalLabel\(typeof signal\.signal/g) ?? [];
    assert.equal(usos.length, 2, `la tabla y las tarjetas móviles usan signalLabel (${usos.length}/2)`);
    assert.ok(!signalsView.includes('formatRecordValue(signal.signal)'), 'sigue la clave en crudo');
  });
});
