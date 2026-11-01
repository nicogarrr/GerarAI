/**
 * Guard: las tarjetas de Joyas se leen solas, sin ISO ni números sueltos.
 *
 * Tester 6 (2026-10-19): (1) la fuente salía en ISO crudo («SEC
 * 2025-12-31:FY + precio 2026-10-16») — el backend la escribe legible
 * («SEC FY2025 + precio 16 oct 2026») con display_es.fecha_es y un periodo
 * «FY2025»; (2) la puntuación era un número suelto: ahora con etiqueta
 * «Puntuación» y escala «/100»; (3) «Gestores 13F que compran» mostraba el
 * número sin unidad: ahora «7 gestores».
 *
 * Ejecutar: node --experimental-strip-types --test scripts/joyas-tarjetas-legibles-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const vista = readFileSync('components/proPicks/GemsView.tsx', 'utf8') + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/propicks.json', 'utf8')).gems);
const formato = readFileSync('components/proPicks/gemsFormat.ts', 'utf8');
const servicio = readFileSync('data-engine/app/services/propicks_gems_service.py', 'utf8');

describe('Joyas: tarjetas legibles', () => {
  it('la fuente sale legible del backend (periodo FY + fecha es), nunca ISO crudo', () => {
    assert.match(servicio, /SEC \{_periodo_es\(g\.fcf_period\)\} \+ precio \{fecha_es/);
    assert.ok(!servicio.includes('+ precio {g.price_date}'), 'sigue la fecha ISO cruda');
    // main #1894 (ejercicios 52/53 semanas): el año ya no es end[:4] a pelo,
    // lo calcula _annual_fiscal_year (cierre 1-7 ene -> FY anterior).
    assert.match(servicio, /return f"\{fp\}\{year\}"/, 'falta el periodo «FY2025»');
    assert.match(servicio, /_annual_fiscal_year\(end, None\)/, 'falta el ajuste 52/53 semanas');
    assert.match(servicio, /SEC 13F, trimestre a \{fecha_es/);
  });

  it('la puntuación lleva etiqueta y escala /100', () => {
    assert.match(vista, /\{t\('propicks\.gems\.score'\)\}/);
    assert.match(vista, /"score":"Puntuación"/);
    assert.ok(vista.includes('/100'), 'falta la escala /100');
  });

  it('los gestores 13F llevan unidad', () => {
    assert.match(formato, /case 'managers_adding_13f':/);
    assert.match(formato, /'gestor' : 'gestores'/);
  });
});
