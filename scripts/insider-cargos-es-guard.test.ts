/**
 * Guard: los cargos insider comunes salen en español; el resto, tal cual.
 *
 * Tester 6 (2026-10-19): cargos en inglés crudo («Chief Legal Officer»).
 * Auditor (2026-10-19): ni una sigla ambigua con lectura inventada (CRO/CCO/
 * CIO/CSO se quedan crudas) ni un cargo rebajado («Assistant Secretary» no es
 * «Secretario»): el patrón consume TODO el título o se muestra el original.
 *
 * Contrato de insiderRole: mapa FIJO de cargos comunes traducidos, compuestos
 * en su orden original («President and CEO» -> «Presidente y CEO»), genéricos
 * sin duplicar («Senior Vice President» no da también «Vicepresidente»),
 * traducción SOLO si el título queda consumido entero, y lo no mapeado o
 * parcial tal cual (nunca se inventa ni se rebaja una traducción).
 *
 * Ejecutar: node --experimental-strip-types --test scripts/insider-cargos-es-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extension .ts explicita la exige node --experimental-strip-types en runtime
const { insiderRole } = await import('../lib/insider/format.ts');

const signalsView = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');

describe('Insider: cargos comunes en español', () => {
  it('traduce los cargos completos del Tester 6', () => {
    assert.equal(insiderRole('Officer', 'Chief Legal Officer'), 'Director jurídico');
    assert.equal(insiderRole('Officer', 'Chief Financial Officer'), 'CFO');
    assert.equal(insiderRole('Officer', 'General Counsel'), 'Asesor jurídico general');
  });

  it('compuestos en el orden del título y siglas asentadas intactas', () => {
    assert.equal(insiderRole('Officer', 'President and CEO'), 'Presidente y CEO');
    assert.equal(insiderRole('Officer', 'EVP & CFO'), 'Vicepresidente ejecutivo y CFO');
    assert.equal(insiderRole('Officer', 'Treasurer and Secretary'), 'Tesorero y Secretario');
  });

  it('el genérico no se come al específico', () => {
    assert.equal(insiderRole('Officer', 'Senior Vice President'), 'Vicepresidente senior');
  });

  it('siglas ambiguas: sin lectura inventada, el título crudo (auditor)', () => {
    // CRO: ¿ingresos o riesgos? CCO: ¿comercial o cumplimiento?
    // CIO: ¿sistemas o inversiones? CSO: ¿estrategia o seguridad?
    assert.equal(insiderRole('Officer', 'CRO'), 'CRO');
    assert.equal(insiderRole('Officer', 'CCO'), 'CCO');
    assert.equal(insiderRole('Officer', 'CIO'), 'CIO');
    assert.equal(insiderRole('Officer', 'CSO'), 'CSO');
    // Deletreado sí traduce: el título dice literalmente lo que es.
    assert.equal(insiderRole('Officer', 'Chief Risk Officer'), 'Director de riesgos');
    assert.equal(insiderRole('Officer', 'Chief Compliance Officer'), 'Director de cumplimiento');
  });

  it('nunca rebaja el cargo: calificadores y áreas devuelven el original (auditor)', () => {
    assert.equal(insiderRole('Officer', 'Assistant Secretary'), 'Assistant Secretary');
    assert.equal(insiderRole('Officer', 'Assistant Treasurer'), 'Assistant Treasurer');
    assert.equal(insiderRole('Officer', 'Co-President'), 'Co-President');
    assert.equal(insiderRole('Officer', 'President, Asia Pacific Division'), 'President, Asia Pacific Division');
    assert.equal(insiderRole('Officer', 'SVP, Global Sales'), 'SVP, Global Sales');
    assert.equal(insiderRole('Officer', 'Chief Strategy and Chief Security Officer'), 'Chief Strategy and Chief Security Officer');
    assert.equal(insiderRole('Officer', 'Vice President of Sales'), 'Vice President of Sales');
    // Government Affairs ya tiene mapa completo; un área adicional sin mapa sigue cruda.
    assert.equal(insiderRole('Officer', 'SVP, GC and Government Affairs, Asia Pacific'), 'SVP, GC and Government Affairs, Asia Pacific');
  });

  it('Government Affairs conserva todas las funciones en orden y Officer es Directivo', () => {
    assert.equal(insiderRole('Officer', 'SVP, GC and Government Affairs'), 'Vicepresidente senior y Asesor jurídico general y Relaciones gubernamentales');
    assert.equal(insiderRole('Officer', 'Officer'), 'Directivo');
  });

  it('la vista de señales pasa por insiderRole (antes mostraba el cargo SEC en crudo)', () => {
    const usos = signalsView.match(/insiderRole\(\s*typeof signal\.role/g) ?? [];
    assert.equal(usos.length, 2, `la tabla y las tarjetas móviles tienen que usar insiderRole (${usos.length}/2)`);
    assert.ok(!signalsView.includes('formatRecordValue(signal.officer_title ?? signal.role)'), 'sigue el cargo en crudo');
  });

  it('lo no mapeado se muestra tal cual y los roles sin título no cambian', () => {
    assert.equal(insiderRole('Officer', 'See remarks'), 'See remarks');
    assert.equal(insiderRole('Director', null), 'Director');
    assert.equal(insiderRole('10% Owner', null), 'Accionista 10 %');
    assert.equal(insiderRole('multiple insiders', null), 'Varios insiders');
  });
});
