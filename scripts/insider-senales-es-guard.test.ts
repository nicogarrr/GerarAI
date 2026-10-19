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
const { signalLabel, signalTooltip } = await import('../lib/insider/format.ts');

const backend = readFileSync('data-engine/app/services/insider_service.py', 'utf8');
const constante = (nombre: string) => {
  const m = backend.match(new RegExp(`^${nombre} = ([0-9_.]+)$`, 'm'));
  assert.ok(m, `falta ${nombre} en insider_service.py`);
  return Number(m[1].replace(/_/g, ''));
};

const signalsView = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');

describe('Insider: claves de señal con etiqueta ES', () => {
  it('traduce las tres claves del monitor', () => {
    assert.equal(signalLabel('cluster_buy'), 'Cluster de compra');
    assert.equal(signalLabel('c_suite_buy'), 'Compra de CEO/CFO');
    assert.equal(signalLabel('big_buy'), 'Gran compra');
  });

  it('clave desconocida: cruda, nunca inventada; vacía: guion', () => {
    assert.equal(signalLabel('future_signal_x'), 'future_signal_x');
    assert.equal(signalLabel(''), '—');
    assert.equal(signalLabel(null), '—');
  });

  it('los tooltips dicen el umbral REAL del backend, leído de la fuente', () => {
    const minInsiders = constante('CLUSTER_MIN_INSIDERS');
    const windowDays = constante('CLUSTER_WINDOW_DAYS');
    const bigUsd = constante('BIG_BUY_THRESHOLD_USD');
    assert.equal(
      signalTooltip('cluster_buy'),
      `${minInsiders} o más insiders distintos compran en ${windowDays} días`,
    );
    assert.equal(signalTooltip('c_suite_buy'), 'El CEO o el CFO compra acciones');
    // El backend usa > estricto (amount > BIG_BUY_THRESHOLD_USD): «supera», nunca «≥».
    assert.match(backend, /amount > BIG_BUY_THRESHOLD_USD/, 'big_buy sigue siendo estricto');
    assert.equal(signalTooltip('big_buy'), `Una compra supera ${bigUsd / 1_000_000} M$`);
    assert.equal(signalTooltip('future_signal_x'), undefined, 'clave desconocida: sin tooltip inventado');
    for (const tooltip of Object.values(signalTooltip ? { a: signalTooltip('cluster_buy'), b: signalTooltip('c_suite_buy'), c: signalTooltip('big_buy') } : {})) {
      assert.ok(!tooltip?.includes('mercado abierto'), 'el código P no siempre es mercado abierto (docstring backend)');
    }
  });

  it('la vista pinta la etiqueta y no la clave cruda', () => {
    const usos = signalsView.match(/signalLabel\(typeof signal\.signal/g) ?? [];
    assert.equal(usos.length, 2, `la tabla y las tarjetas móviles usan signalLabel (${usos.length}/2)`);
    assert.ok(!signalsView.includes('formatRecordValue(signal.signal)'), 'sigue la clave en crudo');
    const tooltips = signalsView.match(/title=\{signalTooltip\(typeof signal\.signal/g) ?? [];
    assert.equal(tooltips.length, 2, 'los dos badges llevan el tooltip con el umbral');
  });
});
