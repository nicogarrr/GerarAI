import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: fila de posición del resumen de inicio a 390 px (recorrido móvil).
 * Revisión del piloto sobre #3523: el NBSP solo no bastaba — la fila quedaba
 * apretada contra el badge y la pista de valor justo se partía por dentro.
 * La fila necesita estructura: columna izquierda flexible (flex-1, SIN min-w-0:
 * badge irrompible (shrink-0), pista VJ en una línea (whitespace-nowrap),
 * gap fijo gap-3 y el «·» pegado al importe con NBSP (rompible después,
 * para poder partir en dos líneas limpias en vez de desbordar).
 */

test('fila de posición: estructura de columnas y separador', () => {
    const src = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
    assert.ok(src.includes('min-h-[44px] flex-wrap items-center justify-between gap-3 p-3 bg-gray-800 rounded-lg'), 'fila con flex-wrap y gap fijo gap-3');
    // 31-oct-2026 (medido en prod a 390px): con el importe como hermano ml-auto,
    // la suma de min-contents cabía y nunca había wrap: la columna encogía por
    // debajo del ancho del chip (~142px) y el chip pintaba encima del importe
    // (chip.right=196 > importe.left=144/163/182 en ASTS/BN/RKLB/UBER). El
    // importe ahora vive en la MISMA fila wrapping que el símbolo, así un
    // salto real lo baja de línea en vez de solaparse.
    assert.ok(src.includes('flex flex-wrap items-center justify-between gap-x-3 gap-y-1'), 'símbolo e importe en la misma fila wrapping');
    assert.ok(src.includes('text-right font-mono text-gray-300'), 'importe alineado a la derecha en la fila del símbolo');
    assert.ok(!src.includes('ml-auto text-right font-mono text-gray-300'), 'el importe ya no es un hermano ml-auto (causaba el solape medido en prod)');
    assert.ok(src.includes('flex min-w-0 flex-1 flex-col gap-1'), 'columna izquierda con min-w-0 para que el flex-wrap decida bien');
    assert.ok(!src.includes('flex min-w-0 flex-wrap items-center gap-1'), 'min-w-0 en chips dejaba desbordar la pista VJ');
    assert.ok(src.includes('whitespace-nowrap text-[11px] text-gray-400'), 'pista VJ sin corte interno');
    assert.ok(src.includes('\\u00a0\\u00b7 ${formatPercent((h.value / portfolioSummary.equityValue)'), '«·» pegado al importe con NBSP');
    assert.ok(!src.includes('\\u00a0\\u00b7\\u00a0${formatPercent'), 'NBSP en ambos lados haría la cadena irrompible y desbordaría');
});

test('badge DCA de la fila no se encoge (shrink-0)', () => {
    const src = readFileSync('components/portfolio/HoldingSignals.tsx', 'utf8');
    assert.ok(src.includes('inline-flex shrink-0 items-center rounded border'), 'DcaLevelChip con shrink-0');
});
