import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: wraps huérfanos a 390 px (recorrido móvil, 31-oct-2026).
 * - La fila de posición de inicio pintaba «12.211,79 € ·» y el peso suelto en
 *   la línea siguiente: el «·» va con NBSP para que valor y peso no se separen.
 * - «Página x de y» se partía («de / 2»): va con whitespace-nowrap; el wrap,
 *   si hace falta, ocurre antes de la frase entera.
 */

test('inicio: valor y peso de una posición no se separan del «·»', () => {
    const src = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
    assert.ok(src.includes('\\u00a0\\u00b7\\u00a0${formatPercent((h.value / portfolioSummary.equityValue)'), 'separador con NBSP');
});

test('«Página x de y» nunca se parte en dos líneas', () => {
    const NOWRAP = 'whitespace-nowrap';
    for (const path of [
        'components/watchlist/WatchlistMembership.tsx',
        'components/research/Pager.tsx',
        'components/research/AnalystTargetsView.tsx',
        'components/watchlist/DcaAlertSettingsList.tsx',
        'app/(root)/research/page.tsx',
        'app/(root)/research/sources/page.tsx',
    ]) {
        const src = readFileSync(path, 'utf8');
        const i = src.indexOf('Página');
        assert.ok(i > 0 && (src.slice(Math.max(0, i - 260), i).includes(NOWRAP) || src.slice(i, i + 400).includes(NOWRAP)), `${path}: «Página» sin nowrap`);
    }
});
