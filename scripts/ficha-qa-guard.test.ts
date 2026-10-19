import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard de los hallazgos QA de la ficha (Nico, 2026-10-19):
 *  (4) "Leer la tesis" con la ultima version en borrador llevaba a
 *      /research/T/tesis vacia (callejon sin salida) y el copy mezclaba
 *      «draft» con "borrador".
 *  (6) En movil el enlace de accion del panel "Calidad financiera segun la
 *      empresa" se pintaba encima del titulo.
 * (10) A 1280px la barra de modulos desbordaba con scrollbar horizontal.
 */

describe('QA ficha: tesis en borrador sin callejon sin salida (4)', () => {
    const tesis = readFileSync('app/(root)/research/[ticker]/tesis/page.tsx', 'utf8');
    it('el estado se muestra traducido, nunca en crudo («draft»)', () => {
        assert.ok(!tesis.includes('«${latest.status}»'), 'no se interpola el status crudo');
        assert.match(tesis, /draft: 'borrador'/, 'mapa de estados con draft traducido');
        assert.ok(tesis.includes('statusLabel(latest.status)'), 'la descripcion usa statusLabel');
    });
    it('el estado vacio ofrece volver a la ficha (no es un callejon)', () => {
        assert.ok(tesis.includes('EmptyLink'), 'usa EmptyLink');
        assert.ok(tesis.includes('?view=thesis`}>Revisar la v'), 'accion al borrador en la ficha');
    });
    it('los botones de exportacion se ocultan sin version publicada (eran un 404)', () => {
        assert.ok(tesis.includes('{published ? ('), 'exportacion condicionada a publicada');
    });
    it('el PDF de la ficha siempre se ofrece: publicada o borrador marcado', () => {
        const menu = readFileSync('components/research/ThesisExportMenu.tsx', 'utf8');
        assert.ok(menu.includes('hasPublished'), 'recibe hasPublished');
        assert.ok(menu.includes('pdf?draft=1'), 'sin publicada baja el borrador');
        const pdfRoute = readFileSync('app/api/thesis/[ticker]/pdf/route.ts', 'utf8');
        assert.ok(pdfRoute.includes("'draft=1'"), 'el borrador lo compone el backend (lista blanca, sin veredicto ni cifras)');
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        assert.ok(page.includes("hasPublished={data.historyDetail.history.some((entry) => entry.status === 'published')}"), 'la ficha lo alimenta');
    });
});

describe('QA ficha: cabecera de panel sin solape en movil (6)', () => {
    it('la cabecera del Panel envuelve las acciones bajo el titulo', () => {
        const panel = readFileSync('components/ui/panel.tsx', 'utf8');
        assert.ok(panel.includes('flex flex-wrap items-start'), 'cabecera con flex-wrap');
    });
});

describe('QA ficha: barra de modulos sin scrollbar en desktop (10)', () => {
    it('el nav de modulos envuelve en todos los tamanos', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        assert.ok(page.includes('mb-7 flex flex-wrap gap-2'), 'modulos envuelven (movil y desktop)');
    });
});
