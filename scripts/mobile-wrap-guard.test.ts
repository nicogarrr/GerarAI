import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: wraps huérfanos a 390 px (recorrido móvil, 31-oct-2026).
 * «Página x de y» se partía («de / 2»): va con whitespace-nowrap; el wrap,
 * si hace falta, ocurre antes de la frase entera.
 * (La fila de posiciones de PersonalizedOverview va en su propio PR:
 * necesita fix de layout, no solo NBSP.)
 */

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
        // El indice de research pinta la posicion por t('research.pageOf'): el texto ES verbatim se comprueba en el dict.
        const migrated = path === 'app/(root)/research/page.tsx' || path === 'components/research/Pager.tsx' || path === 'app/(root)/research/sources/page.tsx' || path === 'components/research/AnalystTargetsView.tsx';
        if (migrated) assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).pageOf, 'Página {current} de {total}');
        const i = src.indexOf(migrated ? 'research.pageOf' : 'Página');
        assert.ok(i > 0 && (src.slice(Math.max(0, i - 260), i).includes(NOWRAP) || src.slice(i, i + 400).includes(NOWRAP)), `${path}: «Página» sin nowrap`);
    }
});
