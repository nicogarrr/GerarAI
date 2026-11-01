/**
 * Guard a11y: el conmutador YTD/1M de Temas tiene semántica de botón.
 *
 * Tester 6 (2026-10-19): «conmutador YTD/1M sin semántica de botón». El
 * control cambia el orden de la lista en la misma página: son <button> con
 * aria-pressed dentro de un role="group" nombrado. El orden sigue en la URL
 * (?orden=1m) vía router.replace con scroll:false, compartible.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/temas-orden-toggle-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const toggle = readFileSync('app/(root)/temas/_components/ThemeOrderToggle.tsx', 'utf8');
const pagina = readFileSync('app/(root)/temas/page.tsx', 'utf8');
const toggleEs = JSON.parse(readFileSync('lib/i18n/messages/es/themes.json', 'utf8')).toggle;

describe('Temas: el conmutador YTD/1M es un grupo de botones con estado', () => {
  it('botones reales con aria-pressed en un grupo nombrado', () => {
    assert.match(toggle, /<button\s/);
    assert.match(toggle, /aria-pressed=\{order === target\}/);
    assert.match(toggle, /role="group"\s+aria-label=\{t\('themes\.toggle\.ariaLabel'\)\}/);
    assert.equal(toggleEs.ariaLabel, 'Ordenar temas por rentabilidad');
  });

  it('el orden sigue en la URL sin perder el scroll', () => {
    assert.ok(toggle.includes("'/temas?orden=1m'"), 'la opción 1M tiene que mantener ?orden=1m');
    assert.match(toggle, /router\.replace\([^,]+, \{ scroll: false \}\)/);
  });

  it('la cabecera usa el toggle, no enlaces sueltos', () => {
    assert.ok(pagina.includes('<ThemeOrderToggle order={order} />'));
    assert.ok(!pagina.includes("aria-current={order === target ? 'page' : undefined}"), 'siguen los enlaces con aria-current');
  });
});
