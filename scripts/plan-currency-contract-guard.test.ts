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
// Las cadenas visibles viven en el diccionario i18n (carril C); los
// componentes las referencian por clave. El guard verifica ambos extremos.
const esPlan = JSON.parse(readFileSync('lib/i18n/messages/es/plan.json', 'utf8'));
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
        const f = view.match(/const planMonthly[\s\S]*?\n    \};/);
        assert.ok(f);
        assert.match(f[0], /plan\.values\.currencyNotRegistered/);
        assert.match(esPlan.values.currencyNotRegistered, /divisa no registrada/);
        assert.match(f[0], /currency_contract_enabled === true/);
    });
    it('la proxima aportacion usa su propia divisa, nunca la base', () => {
        const f = view.match(/const planNext[\s\S]*?(?=\/\*\* Resumen de cuotas previstas)/);
        assert.ok(f);
        assert.match(f[0], /next_contribution_currency/);
        assert.doesNotMatch(f[0], /base_currency/);
        assert.match(view, /next_contribution: planNext/);
    });
    it('cuotas pendientes de vencimiento se informan, no se tratan como error', () => {
        const f = view.match(/const planExpectedPeriods[\s\S]*?\n    \};/);
        assert.ok(f);
        assert.match(f[0], /plan\.values\.periodsPending/);
        assert.match(esPlan.values.periodsPending, /pendientes de vencimiento/);
        assert.match(view, /expected_periods: planExpectedPeriods/);
    });
    it('divisa sin registrar con contrato activo: cuotas no calculables, no ceros', () => {
        const f = view.match(/const planExpectedPeriods[\s\S]*?\n    \};/);
        assert.ok(f);
        assert.match(f[0], /plan\.values\.periodsNotCalculable/);
        assert.equal(esPlan.values.periodsNotCalculable, 'No calculables: divisa no registrada');
        assert.match(f[0], /monthly_currency_recorded !== true/);
    });
    it('las cuotas sin tipo de cambio se resumen en espanol, no como claves crudas', () => {
        const f = view.match(/const planExpectedMissingFx[\s\S]*?\n    \};/);
        assert.ok(f);
        assert.match(f[0], /plan\.values\.expectedMissingFx\b/);
        assert.match(esPlan.values.expectedMissingFx, /sin tipo de cambio/);
        assert.match(view, /expected_missing_fx: planExpectedMissingFx/);
    });
    it('el 409 del contrato se devuelve como resultado y se muestra inline, sin guardar', () => {
        assert.match(actions, /plan_currency_required_for_amount_change/);
        assert.match(actions, /if \(code\) return \{ ok: false, code \}/);
        assert.match(dialog, /if \(!result\.ok\)/);
        assert.match(dialog, /plan\.setup\.errorCurrencyUnavailable/);
        assert.match(esPlan.setup.errorCurrencyUnavailable, /no se ha guardado nada/);
    });
    it('una divisa registrada fuera de la lista se muestra y se conserva (no se enmascara con otra)', () => {
        assert.match(dialog, /currency && !CURRENCY_OPTIONS\.includes\(currency\) \? \[currency, \.\.\.CURRENCY_OPTIONS\]/);
    });
});
