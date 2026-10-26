/** QA 23: el tipo de empresa compuesto no se pinta crudo en la ficha.
 * Ejecución: node --experimental-strip-types --test scripts/company-type-label-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { companyTypeLabel } from '../lib/labels.ts';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('los tipos compuestos se descomponen en factores conocidos', () => {
    assert.equal(companyTypeLabel('space_telecom_pre_fcf'), 'Espacio · Telecomunicaciones · Pre flujo de caja libre');
    assert.equal(companyTypeLabel('biotech_pre_fcf'), 'Biotecnología · Pre flujo de caja libre');
});

test('los tipos simples conservan su etiqueta propia', () => {
    assert.equal(companyTypeLabel('operating_company'), 'empresa operativa');
    assert.equal(companyTypeLabel('research_candidate'), 'candidato de análisis');
    // ai_big_tech (MSFT/META/AMZN/NVDA/AMD en el master) tiene etiqueta
    // exacta: sin ella sus tokens big/tech no son factores y la ficha
    // pintaba el enum crudo.
    assert.equal(companyTypeLabel('ai_big_tech'), 'big tech de IA');
});

test('la etiqueta exacta no es el enum crudo ni lleva guiones bajos', () => {
    const label = companyTypeLabel('ai_big_tech');
    assert.notEqual(label, 'ai_big_tech');
    assert.ok(!label.includes('_'), `la etiqueta no puede contener _: ${label}`);
});

test('los tipos compuestos del master sin factorización tienen etiqueta exacta', () => {
    const exact: Record<string, string> = {
        ai_infra_capacity: 'infraestructura de IA',
        asset_manager_holding: 'holding gestora de activos',
        china_adr_holding: 'holding china (ADR)',
        defense_contract_backlog: 'cartera de contratos de defensa',
        mining_pre_revenue: 'minería pre ingresos',
        platform_fcf_compounder: 'plataforma de crecimiento compuesto de FCL',
        software_ai_disruption: 'software en disrupción por IA',
        software_durable_growth: 'software de crecimiento duradero',
        speculative_scenario: 'escenario especulativo',
    };
    for (const [type, label] of Object.entries(exact)) {
        assert.equal(companyTypeLabel(type), label, type);
        assert.ok(!label.includes('_'), `la etiqueta de ${type} no puede contener _`);
    }
});

test('un token desconocido devuelve el tipo tal cual, nunca inventado', () => {
    assert.equal(companyTypeLabel('algo_que_no_existe'), 'algo_que_no_existe');
});

test('el badge de la cabecera usa la etiqueta, no el valor crudo', () => {
    assert.match(page, /companyTypeLabel\(company\.company_type/);
});
