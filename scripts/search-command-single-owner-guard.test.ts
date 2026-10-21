/**
 * Owner único del diálogo del buscador global (hallazgo QA 2026-10-21):
 * Header monta varias instancias de SearchCommand (botón desktop, icono
 * móvil, drawer) y cada una tenía su propio `open` + listener de Ctrl+K,
 * así que el atajo abría TODOS los diálogos apilados píxel a píxel (dos
 * role="dialog" activos, alerts duplicados, foco/aria confusos, y el
 * error del diálogo oculto persistía). La solución es el store
 * compartido lib/search/search-command-store: una sola instancia dueña
 * monta el CommandDialog y el atajo vive en UN listener global.
 * Ejecución: node --experimental-strip-types --test scripts/search-command-single-owner-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const component = readFileSync('components/SearchCommand.tsx', 'utf8');
const store = readFileSync('lib/search/search-command-store.ts', 'utf8');

void test('las instancias ya no guardan su propio estado open ni listener de teclado', () => {
    assert.doesNotMatch(component, /const \[open, setOpen\]/, 'el open local por instancia reapareció');
    assert.doesNotMatch(component, /window\.addEventListener\("keydown"/, 'el listener por instancia reapareció');
});

void test('el componente consume el store compartido y solo la dueña monta el diálogo', () => {
    assert.match(component, /@\/lib\/search\/search-command-store/);
    assert.match(component, /ownerId === instanceId && \(/, 'el CommandDialog debe montarlo solo la instancia dueña');
    assert.match(component, /closeSearchCommand\(\)/, 'el cierre debe pasar por el store');
});

void test('el store instala exactamente UN listener global de atajos', () => {
    const listeners = store.match(/window\.addEventListener\("keydown"/g) ?? [];
    assert.equal(listeners.length, 1, `listeners globales: ${listeners.length}, esperado 1`);
    assert.match(store, /shortcutListenerInstalled/, 'doble instalación sin guarda');
});

void test('el atajo elige la instancia cuyo gatillo está visible', () => {
    assert.match(store, /isTriggerVisible/, 'sin criterio de visibilidad el atajo no sabe qué instancia abrir');
    assert.match(store, /captureReturnFocus/, 'la devolución de foco necesita saber de dónde se abrió');
});
