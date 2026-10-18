/** FAB-390: a 390px la burbuja del Cerebro no puede tapar en reposo un
 *  control interactivo del borde derecho (boton/enlace bajo ella no se
 *  puede pulsar). Se auto-oculta mientras cruce su zona, haya leyenda o no,
 *  y md+ la mantiene visible siempre. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync('components/brain/GlobalBrain.tsx', 'utf8');

test('el chequeo mira que hay bajo la zona del FAB con elementsFromPoint', () => {
    assert.match(source, /function fabCoversInteractive\(fab: HTMLElement\): boolean/);
    assert.match(source, /document\.elementsFromPoint\(x, y\)/);
    assert.match(source, /getComputedStyle\(fab\)/);
    // Centro + esquinas interiores: un control pequeño en una esquina tambien cuenta.
    assert.match(source, /zoneLeft \+ width \/ 2, zoneTop \+ height \/ 2/);
    assert.match(source, /zoneLeft \+ width - inset, zoneTop \+ height - inset/);
});

test('el propio FAB y su icono no cuentan como obstaculo', () => {
    assert.match(source, /if \(el === fab \|\| fab\.contains\(el\)\) return false;/);
    assert.match(source, /FAB_INTERACTIVE_SELECTOR/);
    assert.match(source, /a\[href\], button, input, select, textarea/);
});

test('el bloqueo por controles se evalua con o sin leyenda y se limpia', () => {
    assert.match(source, /setFabControlsBlocked\(fab \? fabCoversInteractive\(fab\) : false\)/);
    assert.match(source, /fabScrollHidden \|\| fabLegendBlocked \|\| fabControlsBlocked/);
    // La ocultacion sigue siendo solo <md: md+ fuerza visible y clicable.
    assert.match(source, /md:translate-y-0 md:opacity-100 md:pointer-events-auto/);
});

test('F339 se conserva: leyenda, scroll 600 ms y observer', () => {
    assert.match(source, /getElementById\('portfolio-allocation-legend'\)/);
    assert.match(source, /\}, 600\)/);
    assert.match(source, /new MutationObserver\(checkLegendOverlap\)/);
});
