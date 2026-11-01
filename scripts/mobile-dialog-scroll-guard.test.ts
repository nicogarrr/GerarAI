import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: diálogos con formulario nunca cortan su contenido en móvil.
 * Un DialogContent fijo y centrado sin límite de altura: si el contenido
 * supera el viewport (Safari iOS deja ~700px útiles a 390px de ancho),
 * la cabecera y los botones quedan fuera e inalcanzables, sin scroll.
 * Patrón de la casa (AlertsManager): max-h-[90dvh] overflow-y-auto.
 * Quedan fuera confirm-dialog (texto corto fijo) y ui/command (su
 * CommandList ya lleva scroll propio).
 */

const DIALOGS = [
    'components/portfolio/AddTransactionDialog.tsx',
    'components/portfolio/EditTransactionDialog.tsx',
    'components/plan/PlanContributionDialog.tsx',
    'components/plan/PlanSetupDialog.tsx',
    'components/watchlist/WatchlistAddDialog.tsx',
    'components/work-products/WorkProductDialog.tsx',
];

test('todo DialogContent con formulario limita altura y da scroll propio', () => {
    for (const path of DIALOGS) {
        const src = readFileSync(path, 'utf8');
        const i = src.indexOf('<DialogContent');
        assert.ok(i >= 0, `${path}: DialogContent no encontrado`);
        const tag = src.slice(i, src.indexOf('>', i));
        assert.ok(tag.includes('max-h-[90dvh]'), `${path}: DialogContent sin max-h-[90dvh]`);
        assert.ok(tag.includes('overflow-y-auto'), `${path}: DialogContent sin overflow-y-auto`);
    }
});
