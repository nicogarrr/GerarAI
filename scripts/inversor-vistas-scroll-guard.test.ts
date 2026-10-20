import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard: la barra «Vistas de la cartera» del inversor
 * (/inversores/SLUG?vista=) son pestañas con estado en la URL sobre la MISMA
 * página; sin `scroll={false}` cada cambio de vista devuelve al usuario al
 * inicio (mismo bug que las pestañas de la ficha, Nico 2026-10-19).
 */
describe('inversor: las vistas de la cartera conservan el scroll', () => {
    it('el nav de vistas lleva scroll={false}', () => {
        // Nico 2026-10-20 08:30:56: selector de contenido en la ficha, no otra barra.
        const src = readFileSync('app/(root)/inversores/_components/InvestorViewSelector.tsx', 'utf8');
        assert.ok(src.includes('scroll: false'), 'el selector conserva scroll al cambiar ?vista=');
        assert.ok(src.includes('Contenido del inversor'));

    });
});
