/**
 * Guard: la tarjeta del plan no puede esconder la aportación mensual cuando
 * no hay cartera.
 *
 * PLAN_FORMAT formateaba monthly_contribution con planMoney, que devuelve
 * N/D si record.base_currency no es string. Sin cartera el backend devuelve
 * base_currency=null y la tarjeta pintaba «Aportación mensual: N/D» aunque
 * el valor (input crudo del usuario, capturado en € en PlanSetupDialog)
 * estaba en la fuente: reproducido fuente→render (monthly_contribution=500
 * + base_currency=null → N/D). monthly_contribution no es un importe
 * convertido (los *_base sí): sin cartera se muestra en EUR, la divisa del
 * input; los *_base mantienen su N/D honesto (necesitan FX).
 *
 * Ejecución: node --experimental-strip-types --test scripts/plan-monthly-currency-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const view = readFileSync('components/plan/PlanView.tsx', 'utf8');

describe('aportación mensual visible sin cartera', () => {
    it('monthly_contribution no se formatea con el planMoney que exige base_currency', () => {
        const group = view.match(/Object\.fromEntries\(\[([^\]]*)\]\.map\(key => \[key, planMoney\]\)/);
        assert.ok(group, 'grupo planMoney no encontrado');
        assert.doesNotMatch(group[1], /monthly_contribution/);
        assert.match(view, /monthly_contribution: planMonthly/);
    });
    it('sin cartera muestra el importe en la divisa del input (EUR), nunca N/D con dato presente', () => {
        const formatter = view.match(/const planMonthly[\s\S]*?\n    \};/);
        assert.ok(formatter, 'planMonthly no encontrado');
        assert.match(formatter[0], /formatMoney\([^)]*'EUR'\)/);
        // El tramo sin divisa registrada ni contrato (cartera ausente) nunca da N/D.
        const fallback = formatter[0].slice(formatter[0].lastIndexOf('return typeof record.base_currency'));
        assert.doesNotMatch(fallback, /\bNA\b/);
    });
    it('los importes convertidos *_base mantienen planMoney (N/D honesto sin FX)', () => {
        const group = view.match(/Object\.fromEntries\(\[([^\]]*)\]\.map\(key => \[key, planMoney\]\)/);
        assert.ok(group);
        assert.match(group[1], /expected_contributions_base/);
        assert.match(group[1], /gap_base/);
    });
    it('plan legacy con divisa NULL no se pinta en EUR aunque el contrato este apagado', () => {
        const formatter = view.match(/const planMonthly[\s\S]*?\n    \};/);
        assert.ok(formatter, 'planMonthly no encontrado');
        assert.match(formatter[0], /monthly_currency_recorded === false/);
        assert.match(formatter[0], /plan\.values\.currencyNotRegistered/);
        const esPlan = JSON.parse(readFileSync('lib/i18n/messages/es/plan.json', 'utf8'));
        assert.match(esPlan.values.currencyNotRegistered, /divisa no registrada/);
    });
});
