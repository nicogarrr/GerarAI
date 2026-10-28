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

// Gatillo (eager) + paleta (chunk diferido): las aserciones valen para ambos.
const component = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');
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

void test('desmontar a la dueña con el diálogo abierto cierra el store (sin owner huérfano)', () => {
    // Objeción auditor PR#1998: unregister sin cierre dejaba open=true con
    // ownerId muerto y el siguiente Ctrl+K cerraba un fantasma.
    assert.match(store, /state\.ownerId === instance\.id/, 'el unregister no comprueba si la instancia es la dueña');
    const idx = store.indexOf('state.ownerId === instance.id');
    const bloque = store.slice(idx, idx + 200);
    assert.match(bloque, /open: false/, 'el unregister de la dueña no cierra el diálogo');
});
