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
});

test('un token desconocido devuelve el tipo tal cual, nunca inventado', () => {
    assert.equal(companyTypeLabel('algo_que_no_existe'), 'algo_que_no_existe');
});

test('el badge de la cabecera usa la etiqueta, no el valor crudo', () => {
    assert.match(page, /companyTypeLabel\(company\.company_type/);
});
