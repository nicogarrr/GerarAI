/**
 * Guard F288: «Aprobar tesis» deshabilitado (sin versiones, B17) NO puede
 * rendirse con la variante primaria: el bg casi blanco al 50% de opacidad
 * seguía siendo lo más luminoso de /research?view=tesis y se leía como la
 * acción principal activa (affordance engañosa). Deshabilitado se rinde
 * como outline (claramente secundario) + leyenda visible que explica por
 * qué no hay nada que aprobar.
 *
 * Guard de publicación: con la última versión ya publicada la acción ya no
 * existe; el botón tiene que cambiar de estado visual (deshabilitado y
 * «Publicada vX») en lugar de seguir ofreciendo «Aprobar tesis».
 *
 * Ejecución: node --experimental-strip-types --test scripts/thesis-approve-affordance-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source: string = readFileSync(new URL('../components/research/ThesisApproveButton.tsx', import.meta.url), 'utf8');

// Acotamos al botón de aprobar (desde su apertura hasta la de Rechazar).
const approveStart = source.indexOf("onClick={() => decide('approved')}");
const rejectStart = source.indexOf("onClick={() => decide('rejected')}");
assert.ok(approveStart > -1 && rejectStart > approveStart, 'deben existir ambos botones');
const approveSection = source.slice(source.lastIndexOf('<Button', approveStart), rejectStart);

void test('el botón Aprobar no usa la variante primaria cuando está bloqueado', () => {
    // La variante debe ser condicional al bloqueo (sin versiones, ya publicada
    // o estado no aprobable); un botón aprobar sin `variant` renderiza
    // `default` (primario casi blanco) siempre.
    assert.match(
        approveSection,
        /variant=\{approveBlocked \? 'outline' : 'default'\}/,
        'Aprobar bloqueado debe rendirse como outline, no como primario',
    );
    assert.match(
        approveSection,
        /disabled=\{approveBlocked \|\| pending !== null\}/,
        'Aprobar bloqueado debe quedar deshabilitado',
    );
});

void test('el estado sin versiones se explica con una leyenda visible', () => {
    // Tooltip solo no basta: el motivo del disabled debe leerse en pantalla.
    assert.match(
        source,
        /t\('research\.thesisApprove\.noVersions'\)/,
        'debe existir la leyenda «Sin versiones de tesis que aprobar o rechazar.»',
    );
    assert.equal(
        JSON.parse(readFileSync(new URL('../lib/i18n/messages/es/research.json', import.meta.url), 'utf8')).thesisApprove.noVersions,
        'Sin versiones de tesis que aprobar o rechazar.',
    );
    assert.match(
        source,
        /\{blockNote \? \(\s*<span/,
        'la leyenda (blockNote) debe renderizarse visible junto al botón',
    );
});

void test('con la última versión publicada el botón dice «Publicada vX»', () => {
    assert.match(
        source,
        /alreadyPublished = latestStatus === 'published'/,
        'el estado publicado debe derivarse de latestStatus',
    );
    assert.match(
        source,
        /alreadyPublished \|\| notApprovableReason !== undefined/,
        'ya publicada debe bloquear la acción de aprobar',
    );
    assert.match(
        approveSection,
        /alreadyPublished\s*\?\s*t\('research\.thesisApprove\.published', \{ version: latestVersion \?\? '\?' \}\)/,
        'el botón debe cambiar su etiqueta a «Publicada vX» tras publicar',
    );
});
