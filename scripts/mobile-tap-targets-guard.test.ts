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
        const i = page.indexOf('>Research</Link>');
        assert.ok(i > 0, 'Research existe');
        assert.ok(page.slice(page.lastIndexOf('<Link', i), i).includes(AREA), 'Research con area tactil');
        // Los enlaces secundarios viven en el menú de cabecera.
        const menu = readFileSync('components/research/CompanyActionsMenu.tsx', 'utf8');
        const item = menu.match(/const ITEM = '([^']+)'/)?.[1] ?? '';
        assert.ok(item.includes(AREA), 'enlaces del menu con area tactil');
        for (const texto of ['Qué ha cambiado', 'Cortos públicos', 'Noticias', 'Insiders', 'Dividendos y splits']) {
            assert.ok(menu.includes(texto), `${texto} en el menu`);
        }
        assert.ok(menu.includes('size-11'), 'boton del menu de 44px');
    });
    it('boton Guia de investigacion y conmutador Saldos/Emisiones', () => {
        const guide = readFileSync('components/research/GuideBrainButton.tsx', 'utf8');
        assert.ok(guide.includes(AREA), 'GuideBrainButton con area tactil');
        const panel = readFileSync('components/research/ShareCapitalPanel.tsx', 'utf8');
        const group = panel.slice(panel.indexOf('aria-label="Tipo de historial"'), panel.indexOf('aria-label="Tipo de historial"') + 900);
        assert.ok((group.match(new RegExp(AREA.replace(/[[\]]/g, '\\$&'), 'g')) ?? []).length === 2, 'ambos botones del conmutador con area tactil');
    });
    it('las subrutas históricas redirigen a su sección; la navegación es la fila de pestañas (29-oct-2026)', () => {
        // Ya no hay enlaces de retorno: las subrutas llevan a su sección de
        // la pestaña y la fila de seis pestañas (44px por pestaña) es toda
        // la navegación de la ficha.
        for (const p of ['financial-terminal', 'driver-assumptions', 'management-credibility', 'decision-lessons', 'share-capital']) {
            const page = readFileSync(`app/(root)/research/[ticker]/${p}/page.tsx`, 'utf8');
            assert.ok(page.includes('redirect('), `${p}: conserva su URL con redirect a la sección`);
        }
        const shorts = readFileSync('app/(root)/research/[ticker]/shorts/page.tsx', 'utf8');
        assert.ok(shorts.includes(`inline-flex ${AREA} items-center text-teal-300 sm:min-h-0`), 'shorts: enlace de retorno con area tactil');
        const nav = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');
        assert.ok(nav.includes(`min-h-[44px]`), 'pestañas con area tactil');
    });
    it('historial de versiones de supuestos con area tactil', () => {
        // Los supuestos son una sección de la pestaña Valoración desde el 29-oct-2026.
        const section = readFileSync('components/research/sections/DriverAssumptionsSection.tsx', 'utf8');
        assert.ok(section.includes('<summary className="cursor-pointer py-2.5'), 'summary con padding tactil en movil');
    });
});

describe('móvil: 44 px en biblioteca, estados vacíos y enlaces de panel (auditoría 375 px, 2026-10-27)', () => {
    it('biblioteca abre Cerebro y controles de doctrina tienen área táctil', () => {
        const entry = readFileSync('app/(root)/inversores/_components/LibraryChat.tsx', 'utf8');
        const chat = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
        assert.ok(entry.includes('BRAIN_LIBRARY_CONTEXT_ID') && entry.includes('h-11'), 'entrada compacta táctil que abre el Cerebro flotante');
        assert.ok(chat.includes('className="flex min-h-11 items-center gap-2"'), 'casilla de análisis táctil');
        assert.ok(chat.includes('block min-h-11 w-full'), 'selector de autor táctil');
        assert.ok(chat.includes('mt-2 block min-h-11'), 'copiar táctil');
    });
    it('EmptyLink (CTA de los estados vacíos)', () => {
        const empty = readFileSync('components/ui/empty-state.tsx', 'utf8');
        assert.ok(empty.includes(`'inline-flex ${AREA} sm:min-h-0 items-center gap-2 rounded-md border border-teal-800`), 'EmptyLink con area tactil');
    });
    it('enlaces de acción de los paneles de la ficha', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        for (const texto of ['Ver todas', 'Ver todos los cambios']) {
            const i = page.indexOf(`              ${texto}\n`);
            assert.ok(i > 0, `${texto} existe`);
            assert.ok(page.slice(page.lastIndexOf('<Link', i), i).includes(AREA), `${texto} con area tactil`);
        }
        const own = readFileSync('components/research/OwnershipSignalsPanel.tsx', 'utf8');
        assert.ok(own.includes(`inline-flex ${AREA} sm:min-h-0 items-center text-sm text-teal-300" href={holdersHref}`), 'Ver propietarios con area tactil');
    });
});
