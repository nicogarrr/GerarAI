/**
 * Guard: los cargos insider comunes salen en español; el resto, tal cual.
 *
 * Tester 6 (2026-10-19): cargos en inglés crudo («SVP, GC and Government
 * Affairs», «Chief Legal Officer»). Contrato de insiderRole: mapa FIJO de
 * cargos comunes traducidos, compuestos en su orden original («President and
 * CEO» -> «Presidente y CEO»), genéricos sin duplicar («Senior Vice
 * President» no da también «Vicepresidente») y lo no mapeado tal cual
 * (nunca se inventa una traducción).
 *
 * Ejecutar: node --experimental-strip-types --test scripts/insider-cargos-es-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { insiderRole } from '../lib/insider/format.ts';

describe('Insider: cargos comunes en español', () => {
  it('traduce los cargos del Tester 6', () => {
    assert.equal(insiderRole('Officer', 'Chief Legal Officer'), 'Director jurídico');
    assert.equal(insiderRole('Officer', 'SVP, GC and Government Affairs'), 'Vicepresidente senior y Asesor jurídico general');
  });

  it('compuestos en el orden del título y siglas ya asentadas intactas', () => {
    assert.equal(insiderRole('Officer', 'President and CEO'), 'Presidente y CEO');
    assert.equal(insiderRole('Officer', 'EVP & CFO'), 'Vicepresidente ejecutivo y CFO');
    assert.equal(insiderRole('Officer', 'Treasurer and Secretary'), 'Tesorero y Secretario');
  });

  it('el genérico no se come al específico', () => {
    assert.equal(insiderRole('Officer', 'Senior Vice President'), 'Vicepresidente senior');
    assert.equal(insiderRole('Officer', 'Vice President of Sales'), 'Vicepresidente');
  });

  it('lo no mapeado se muestra tal cual y los roles sin título no cambian', () => {
    assert.equal(insiderRole('Officer', 'See remarks'), 'See remarks');
    assert.equal(insiderRole('Director', null), 'Director');
    assert.equal(insiderRole('10% Owner', null), 'Accionista 10 %');
    assert.equal(insiderRole('multiple insiders', null), 'Varios insiders');
  });
});
