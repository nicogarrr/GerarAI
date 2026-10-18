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
        const src = readFileSync('app/(root)/inversores/[slug]/page.tsx', 'utf8');
        const labelAt = src.indexOf('aria-label="Vistas de la cartera"');
        assert.ok(labelAt > 0, 'nav "Vistas de la cartera" existe');
        const start = src.lastIndexOf('<nav', labelAt);
        const end = src.indexOf('</nav>', labelAt);
        assert.ok(start >= 0 && end > labelAt, 'el nav esta bien formado');
        const nav = src.slice(start, end);
        assert.ok(nav.includes('scroll={false}'), 'las vistas ?vista= llevan scroll={false}');
    });
});
