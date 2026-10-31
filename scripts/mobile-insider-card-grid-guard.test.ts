import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: la tarjeta móvil del feed de insiders no desborda su celda de
 * importe a 390px (medido 2026-10-31). Con grid-cols-3 fijas, un importe
 * con NBSP de Intl es-ES a partir de ~100M$ ("8.535.000.000 $", 116px)
 * desborda la celda de 103px y sangra fuera de la tarjeta: el NBSP no
 * permite partir el número. Dos columnas en móvil (159px) lo alojan;
 * las tres columnas vuelven en sm+.
 */

test('tarjeta insider: 2 columnas en móvil, 3 desde sm', () => {
    const src = readFileSync('components/insider/InsiderFeed.tsx', 'utf8');
    assert.ok(
        src.includes('grid grid-cols-2 gap-2 text-sm sm:grid-cols-3'),
        'dl de la tarjeta con grid-cols-2 sm:grid-cols-3',
    );
    assert.ok(
        !src.includes('grid grid-cols-3 gap-2 text-sm"'),
        'sin grid-cols-3 fija en la tarjeta móvil',
    );
});
