/**
 * Insiders (Form 4) y 13F en la ficha y en la tesis (conexión 10b).
 *
 * Funciones reales de lib/research/ownership-signals.ts + cableado mínimo.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/ownership-signals.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { holderChangeLabel, holdersLines, holdersTone, insiderLines, insiderTone, ownershipMoney } from '../lib/research/ownership-signals.ts';

const insiderOk = {
  status: 'ok' as const,
  window_days: 180,
  source: 'SEC EDGAR · Form 4',
  buys: { trades: 3, insiders: 3, shares: 300, value: 15000 },
  sells: { trades: 1, insiders: 1, shares: 2000, value: 160000, planned_10b5_1: 1 },
  net_value: -145000,
  cluster_buying: true,
  last_date: '2026-10-01',
  reading: 'Compras en grupo de insiders (3 o más)',
};

const holdersOk = {
  status: 'ok' as const,
  source: 'SEC EDGAR · Form 13F',
  holders_count: 2,
  managers_with_data: 5,
  report_date: '2026-09-30',
  total_value_usd: 10_000_000,
  changes: { new: 1, increased: 1, decreased: 0, closed: 1 },
  top_holders: [{ name: 'Fundsmith', value_usd: 9_000_000, change: 'increased' as const }],
  exited: ['Pershing Square'],
  limitations: [],
};

describe('ownership-signals', () => {
  it('formatea importes en USD es-ES', () => {
    assert.match(ownershipMoney(113100), /^113\.100\s?US\$$/);
    assert.match(ownershipMoney(-145000), /^-145\.000\s?US\$$/);
  });

  it('las compras en grupo pesan más que el saldo neto vendedor', () => {
    assert.equal(insiderTone(insiderOk), 'positivo');
    assert.equal(insiderTone({ ...insiderOk, cluster_buying: false }), 'negativo');
    assert.equal(insiderTone({ status: 'sin_datos' }), 'neutro');
  });

  it('líneas insider con plan 10b5-1 y última fecha', () => {
    const lines = insiderLines(insiderOk);
    assert.equal(lines.length, 3);
    assert.match(lines[1], /1 con plan 10b5-1/);
    assert.match(lines[2], /última operación 2026-10-01/);
    assert.deepEqual(insiderLines({ status: 'sin_datos', detail: 'Sin Form 4.' }), ['Sin Form 4.']);
  });

  it('13F: tono por entradas frente a salidas y gestores que salen', () => {
    assert.equal(holdersTone(holdersOk), 'positivo');
    assert.equal(holdersTone({ ...holdersOk, changes: { new: 0, increased: 0, decreased: 1, closed: 1 } }), 'negativo');
    const lines = holdersLines(holdersOk);
    assert.match(lines[0], /^2 de 5 gestores revisados lo declaran \(13F de 2026-09-30\)/);
    assert.match(lines[1], /1 nuevas, 1 aumentan, 0 reducen, 1 salen/);
    assert.equal(lines[2], 'Salen: Pershing Square.');
    assert.equal(holderChangeLabel('new'), 'nueva posición');
    assert.equal(holderChangeLabel(null), 'sin comparación');
  });

  it('la ficha pinta el panel en el resumen', () => {
    const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    assert.match(page, /<OwnershipSignalsPanel /);
    assert.match(page, /getOwnershipSignals\(ticker\)/);
    const actions = readFileSync('lib/actions/insider.actions.ts', 'utf8');
    assert.match(actions, /\/api\/insider\/ownership-signals\?/);
  });
});
