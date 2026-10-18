import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard: area tactil minima de 44px en movil (QA ficha 390px, 2026-10-19).
 * Los enlaces y botones de la ficha y sus subrutas medidos en prod a 390px
 * tenian 15-36px de alto; la convencion del repo es `min-h-[44px] sm:min-h-0`.
 */

const AREA = 'min-h-[44px]';

describe('ficha movil: objetivos tactiles de al menos 44px', () => {
    it('enlaces de la cabecera de la ficha', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        for (const texto of ['Cortos públicos', 'Noticias</Link>', 'Insiders</Link>', 'Dividendos y splits', '>Research</Link>']) {
            const i = page.indexOf(texto);
            assert.ok(i > 0, `${texto} existe`);
            const tag = page.slice(page.lastIndexOf('<Link', i), i);
            assert.ok(tag.includes(AREA), `${texto} con ${AREA}`);
        }
        const cambios = page.indexOf('Qué ha cambiado');
        assert.ok(page.slice(page.lastIndexOf('<Link', cambios), cambios).includes(AREA), 'Qué ha cambiado con area tactil');
    });
    it('boton Guia de investigacion y conmutador Saldos/Emisiones', () => {
        const guide = readFileSync('components/research/GuideBrainButton.tsx', 'utf8');
        assert.ok(guide.includes(AREA), 'GuideBrainButton con area tactil');
        const panel = readFileSync('components/research/ShareCapitalPanel.tsx', 'utf8');
        const group = panel.slice(panel.indexOf('aria-label="Tipo de historial"'), panel.indexOf('aria-label="Tipo de historial"') + 900);
        assert.ok((group.match(new RegExp(AREA.replace(/[[\]]/g, '\\$&'), 'g')) ?? []).length === 2, 'ambos botones del conmutador con area tactil');
    });
    it('enlaces de retorno de las subrutas', () => {
        for (const p of ['financial-terminal', 'driver-assumptions', 'management-credibility', 'decision-lessons']) {
            const page = readFileSync(`app/(root)/research/[ticker]/${p}/page.tsx`, 'utf8');
            assert.ok(page.includes(`className="${AREA} sm:min-h-0" size="sm"`), `${p}: boton de retorno con area tactil`);
        }
        for (const p of ['share-capital', 'shorts']) {
            const page = readFileSync(`app/(root)/research/[ticker]/${p}/page.tsx`, 'utf8');
            assert.ok(page.includes(`inline-flex ${AREA} items-center text-teal-300 sm:min-h-0`), `${p}: enlace de retorno con area tactil`);
        }
    });
    it('historial de versiones de supuestos con area tactil', () => {
        const page = readFileSync('app/(root)/research/[ticker]/driver-assumptions/page.tsx', 'utf8');
        assert.ok(page.includes('<summary className="cursor-pointer py-2.5'), 'summary con padding tactil en movil');
    });
});
