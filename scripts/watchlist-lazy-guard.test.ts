/**
 * Guard de bundle: el diálogo de alta y las islas del panel DCA de
 * /watchlist cargan diferidos (next/dynamic), para que su JS no viaje en el
 * bundle inicial de la ruta. Si alguien vuelve a imports estáticos,
 * /watchlist recupera varios KB gz de JS inicial y este guard lo pilla.
 * Ejecución: node --experimental-strip-types --test scripts/watchlist-lazy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const button = readFileSync('components/watchlist/WatchlistAddButton.tsx', 'utf8');
const dialog = readFileSync('components/watchlist/WatchlistAddDialog.tsx', 'utf8');
const panel = readFileSync('components/watchlist/DcaSignalsPanel.tsx', 'utf8');
const settings = readFileSync('components/watchlist/DcaAlertSettingsList.tsx', 'utf8');
const lazy = readFileSync('components/watchlist/LazyDcaControls.tsx', 'utf8');

describe('watchlist: diálogo de alta diferido', () => {
    it('el contenido con el buscador carga con dynamic() desde el botón', () => {
        assert.ok(button.includes("import('./WatchlistAddDialog')"), 'el diálogo debe ser un import dinámico');
        assert.ok(!button.includes('TickerSearchInput'), 'el buscador vive en el diálogo, no en el botón');
    });

    it('el chunk se precarga al rozar el gatillo y queda montado tras abrir', () => {
        assert.ok(button.includes('onPointerDown'), 'precarga en pointerdown');
        assert.ok(button.includes('onFocus'), 'precarga en focus');
        assert.ok(button.includes('openedOnce'), 'el botón recuerda la primera apertura');
    });

    it('el diálogo conserva el alta (buscador compartido + alta manual)', () => {
        assert.ok(dialog.includes('TickerSearchInput'), 'el buscador compartido está en el diálogo');
        assert.ok(dialog.includes('addToWatchlistCanonical'), 'la server action se invoca desde el diálogo');
        assert.ok(dialog.includes('Ya sigues'), 'el aviso de ticker ya seguido se conserva');
    });
});

describe('watchlist: islas del panel DCA diferidas', () => {
    it('el panel consume las versiones perezosas, sin imports estáticos de las islas', () => {
        assert.ok((panel + settings).includes("from '@/components/watchlist/LazyDcaControls'"), 'el panel debe usar la frontera perezosa');
        for (const isla of ['DcaEvaluateButton', 'DcaHitRatesPopover', 'DcaMinLevelSelect']) {
            assert.ok(!(panel + settings).includes(`import ${isla} from`), `${isla} no debe tener import estático en el panel`);
            assert.ok(lazy.includes(`dynamic(() => import('@/components/watchlist/${isla}')`), `${isla} debe cargar con dynamic()`);
        }
    });

    it('las islas diferidas declaran un fallback con role=status', () => {
        assert.ok(lazy.includes('role="status"'), 'el fallback anuncia la carga');
    });
});
