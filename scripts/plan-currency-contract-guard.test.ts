/**
 * Guard: contrato de divisa del plan (frontend, stacked sobre el backend).
 * - El selector solo existe con la capability del backend y NO preselecciona.
 * - Solo se envia monthly_contribution_currency con la capability (flag OFF
 *   no habilita el contrato nuevo).
 * - Plan legacy sin divisa: importe crudo + «divisa no registrada», sin simbolo.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/plan-currency-contract-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const dialog = readFileSync('components/plan/PlanSetupDialog.tsx', 'utf8');
const view = readFileSync('components/plan/PlanView.tsx', 'utf8');
const actions = readFileSync('lib/actions/plan.actions.ts', 'utf8');

describe('selector de divisa del plan', () => {
    it('depende de la capability del backend, no de un flag del cliente', () => {
        assert.match(dialog, /currencyEnabled = initial\?\.currency_contract_enabled === true/);
    });
    it('no preselecciona divisa: el estado inicial sale solo de la divisa registrada', () => {
        assert.match(dialog, /useState\(\(\) => asText\(initial\?\.monthly_contribution_currency\)\.toUpperCase\(\)\)/);
        assert.doesNotMatch(dialog, /useState\(\(\) => asText\(initial\?\.monthly_contribution_currency\)[^;]*\|\| '(EUR|USD)'/);
    });
    it('bloquea el envio sin divisa elegida', () => {
        assert.match(dialog, /currencyEnabled && !currency/);
    });
    it('solo envia la divisa con capability (OFF no usa el contrato nuevo)', () => {
        assert.match(dialog, /\.\.\.\(currencyEnabled \? \{ monthly_contribution_currency: currency \} : \{\}\)/);
    });
    it('el payload la declara opcional (omitir conserva la registrada)', () => {
        assert.match(actions, /monthly_contribution_currency\?: string/);
    });
});

describe('visualizacion del importe', () => {
    it('plan legacy con contrato activo: importe crudo y «divisa no registrada»', () => {
        const f = view.match(/const planMonthly[\s\S]*?\n};/);
        assert.ok(f);
        assert.match(f[0], /divisa no registrada/);
        assert.match(f[0], /currency_contract_enabled === true/);
    });
    it('la proxima aportacion usa su propia divisa, nunca la base', () => {
        const f = view.match(/const planNext[\s\S]*?const PLAN_FORMAT/);
        assert.ok(f);
        assert.match(f[0], /next_contribution_currency/);
        assert.doesNotMatch(f[0], /base_currency/);
        assert.match(view, /next_contribution: planNext/);
    });
});
