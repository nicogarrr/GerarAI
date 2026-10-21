/**
 * Owner huérfano del buscador global (objeción auditor PR#1998): si la
 * instancia dueña se desmonta con el diálogo abierto (el drawer móvil se
 * cierra por Escape o al cruzar el breakpoint), el store quedaba
 * open=true con ownerId apuntando a una instancia muerta y el siguiente
 * Ctrl+K solo "cerraba" un diálogo fantasma. El unregister debe cerrar.
 * Ejecución: node --experimental-strip-types --test scripts/search-command-owner-unregister.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097
import { registerSearchCommandInstance, openSearchCommand, closeSearchCommand, getSearchCommandSnapshot } from '../lib/search/search-command-store.ts';

function fakeInstance(id: string, visible = true) {
    return {
        id,
        isTriggerVisible: () => visible,
        captureReturnFocus: () => {},
    };
}

void test('desmontar a la dueña con el diálogo abierto cierra el store (sin owner huérfano)', () => {
    const unregisterA = registerSearchCommandInstance(fakeInstance('A'));
    const unregisterB = registerSearchCommandInstance(fakeInstance('B'));
    openSearchCommand('A');
    assert.deepEqual(getSearchCommandSnapshot(), { open: true, ownerId: 'A' });

    unregisterA(); // la dueña se desmonta (drawer cerrado / breakpoint)
    assert.deepEqual(
        getSearchCommandSnapshot(),
        { open: false, ownerId: null },
        'quedó open=true con owner huérfano: el siguiente Ctrl+K cerraría un fantasma',
    );

    // La siguiente apertura funciona contra otra instancia viva.
    openSearchCommand('B');
    assert.deepEqual(getSearchCommandSnapshot(), { open: true, ownerId: 'B' });
    closeSearchCommand();
    unregisterB();
});

void test('desmontar una instancia NO dueña no toca el diálogo abierto', () => {
    const unregisterA = registerSearchCommandInstance(fakeInstance('A'));
    const unregisterB = registerSearchCommandInstance(fakeInstance('B'));
    openSearchCommand('A');
    unregisterB();
    assert.deepEqual(getSearchCommandSnapshot(), { open: true, ownerId: 'A' });
    closeSearchCommand();
    // Tras el cierre normal el owner queda sticky (animación/foco de Radix).
    assert.deepEqual(getSearchCommandSnapshot(), { open: false, ownerId: 'A' });
    unregisterA();
});

void test('desmontar a la dueña con el diálogo ya cerrado es no-op', () => {
    const unregisterA = registerSearchCommandInstance(fakeInstance('A'));
    openSearchCommand('A');
    closeSearchCommand();
    unregisterA();
    assert.deepEqual(getSearchCommandSnapshot(), { open: false, ownerId: null });
});
