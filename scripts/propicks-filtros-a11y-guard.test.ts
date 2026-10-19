/**
 * Guard a11y: los controles de los filtros ProPicks llevan nombre accesible.
 *
 * Tester 6 (2026-10-19): «sliders y desplegables de filtros sin semántica».
 * Los roles ya los da Radix (role="slider" en el thumb, role="combobox" en el
 * trigger, role="listbox" en el contenido), pero el <Label> suelto no nombra
 * nada: un <label> sin htmlFor no etiqueta un span[role=slider] ni un
 * button[role=combobox]. Contrato: cada control va ligado a su etiqueta con
 * aria-labelledby, y ui/slider.tsx reenvía aria-label/labelledby al THUMB
 * (el elemento con role="slider"), no a la raíz contenedora.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-filtros-a11y-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const filtros = readFileSync('components/proPicks/EnhancedProPicksFilters.tsx', 'utf8');
const slider = readFileSync('components/ui/slider.tsx', 'utf8');

describe('ProPicks: filtros con nombre accesible', () => {
  it('ui/slider reenvía aria-label/aria-labelledby al thumb (role="slider")', () => {
    assert.match(
      slider,
      /<SliderPrimitive\.Thumb\s+aria-label=\{ariaLabel\}\s+aria-labelledby=\{ariaLabelledby\}/,
      'el aria del Slider tiene que caer en el thumb, no en la raíz',
    );
  });

  it('cada slider va ligado a su etiqueta', () => {
    assert.ok(filtros.includes('id="propicks-filtro-limit-label"'), 'falta la etiqueta de Cantidad');
    assert.ok(filtros.includes('aria-labelledby="propicks-filtro-limit-label"'), 'slider de Cantidad sin nombre');
    assert.ok(filtros.includes('id="propicks-filtro-minscore-label"'), 'falta la etiqueta de Puntuación mínima');
    assert.ok(filtros.includes('aria-labelledby="propicks-filtro-minscore-label"'), 'slider de Puntuación sin nombre');
  });

  it('cada desplegable va ligado a su etiqueta', () => {
    assert.ok(filtros.includes('id="propicks-filtro-sector-label"'), 'falta la etiqueta de Sector');
    assert.ok(filtros.includes('aria-labelledby="propicks-filtro-sector-label"'), 'select de Sector sin nombre');
    assert.ok(filtros.includes('id="propicks-filtro-sortby-label"'), 'falta la etiqueta de Ordenar por');
    assert.ok(filtros.includes('aria-labelledby="propicks-filtro-sortby-label"'), 'select de Ordenar sin nombre');
  });
});
