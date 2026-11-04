/**
 * Guardia de lib/research/valuation-blockers.ts: catálogo de causas del
 * «sin DCF» del modelo a largo plazo y sus claves i18n. Corre con node
 * (strip-types), sin vitest: node scripts/valuation-blockers-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  modelUnvaluedCauseKeys,
  scenarioValuationCause,
  VALUATION_BLOCKER_KEYS,
  valuationBlockerKey,
// @ts-expect-error Node strip-types requires the explicit TS extension.
} from '../lib/research/valuation-blockers.ts';

const es = JSON.parse(readFileSync(new URL('../lib/i18n/messages/es/research.json', import.meta.url), 'utf8'));
const en = JSON.parse(readFileSync(new URL('../lib/i18n/messages/en/research.json', import.meta.url), 'utf8'));

// Cada token del catálogo resuelve a una clave existente en es y en.
for (const [token, key] of Object.entries(VALUATION_BLOCKER_KEYS)) {
  assert.ok(token === token.toLowerCase() && !token.includes(' '), `token máquina: ${token}`);
  const path = key.replace(/^research\./, '').split('.');
  const lookup = (dict: Record<string, unknown>) =>
    path.reduce<unknown>((node, part) => (node == null ? node : (node as Record<string, unknown>)[part]), dict);
  assert.equal(typeof lookup(es), 'string', `falta ${key} en es/research.json`);
  assert.equal(typeof lookup(en), 'string', `falta ${key} en en/research.json`);
}
assert.equal(valuationBlockerKey('token_inventado'), null);

const esT = (key: string) => key.split('.').pop() ?? key;

// Con valoración no hay causa; sin ella, tokens unidos y traducidos.
assert.equal(scenarioValuationCause({ valuation: { value_per_share: 1 } }, esT), null);
assert.equal(
  scenarioValuationCause({ valuation: null, valuation_blockers: ['current_net_debt_missing', 'terminal_shares_missing'] }, esT),
  'currentNetDebtMissing · terminalSharesMissing',
);
// Token desconocido: cae a la nota original del backend, nunca se oculta.
assert.equal(
  scenarioValuationCause({ valuation: null, valuation_blockers: ['otro'], valuation_note: 'DCF skipped: raw.' }, esT),
  'DCF skipped: raw.',
);
// Sin blockers (snapshot antiguo): la nota en crudo; sin nada, null.
assert.equal(scenarioValuationCause({ valuation: null, valuation_note: 'DCF skipped: raw.' }, esT), 'DCF skipped: raw.');
assert.equal(scenarioValuationCause({ valuation: null }, esT), null);

// Cabecera: solo cuando TODOS los escenarios carecen de valoración; sin repetir.
assert.deepEqual(modelUnvaluedCauseKeys({}), []);
assert.deepEqual(
  modelUnvaluedCauseKeys({ a: { valuation: null }, b: { valuation: { value_per_share: 1 } } }),
  [],
);
assert.deepEqual(
  modelUnvaluedCauseKeys({
    a: { valuation: null, valuation_blockers: ['terminal_shares_missing'] },
    b: { valuation: null, valuation_blockers: ['terminal_shares_missing', 'current_net_debt_missing'] },
  }),
  [
    'research.model.valuationBlocker.terminalSharesMissing',
    'research.model.valuationBlocker.currentNetDebtMissing',
  ],
);

console.log('valuation-blockers-guard: ok');
