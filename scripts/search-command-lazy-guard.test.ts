/**
 * Guard de rendimiento móvil: cmdk y la lógica de búsqueda (~42 KB gzip)
 * no pueden viajar en el bundle inicial de las páginas autenticadas. El
 * gatillo y el atajo Ctrl+K se quedan eager en SearchCommand.tsx; la paleta
 * es un chunk diferido que solo se descarga al abrir el buscador.
 *
 * Medida (build local): /watchlist 131,1 -> ~89 KB gzip de JS inicial;
 * el resto de páginas autenticadas baja la misma cantidad.
 *
 * Ejecución: node --experimental-strip-types --test scripts/search-command-lazy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const trigger = readFileSync('components/SearchCommand.tsx', 'utf8');
const dialog = readFileSync('components/SearchCommandDialog.tsx', 'utf8');
const header = readFileSync('components/Header.tsx', 'utf8');

describe('buscador global: paleta diferida, gatillo y atajo eager', () => {
    it('el gatillo no importa la paleta ni cmdk en estático', () => {
        assert.ok(!/from\s+['"]@\/components\/ui\/command['"]/.test(trigger), 'SearchCommand no debe importar ui/command');
        assert.ok(!/from\s+['"]cmdk['"]/.test(trigger), 'SearchCommand no debe importar cmdk');
        assert.match(trigger, /dynamic\(\(\) => import\('@\/components\/SearchCommandDialog'\)/);
    });

    it('la paleta es quien usa cmdk y la búsqueda', () => {
        assert.match(dialog, /from\s+"@\/components\/ui\/command"/);
        assert.match(dialog, /searchStocksWithStatus/);
    });

    it('el atajo Ctrl+K y el owner único se registran eager (funcionan desde el primer pintado)', () => {
        assert.match(trigger, /ensureSearchCommandShortcutListener\(\)/);
        assert.match(trigger, /registerSearchCommandInstance\(/);
        assert.match(trigger, /openSearchCommand\(instanceId\)/);
    });

    it('Header sigue importando el gatillo (no la paleta)', () => {
        assert.match(header, /import SearchCommand from '@\/components\/SearchCommand'/);
        assert.ok(!/SearchCommandDialog/.test(header));
    });

    it('la primera apertura precarga el chunk (pointerdown/focus llegan antes que click)', () => {
        assert.match(trigger, /preloadDialog/);
        assert.match(trigger, /onPointerDown=\{preloadDialog\}/);
    });

    it('la devolución de foco al cerrar sigue llegando al gatillo', () => {
        assert.match(trigger, /getFocusTarget/);
        assert.match(dialog, /getFocusTarget\(\)\?\.focus\(\)/);
    });
});
