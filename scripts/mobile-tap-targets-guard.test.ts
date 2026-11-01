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
        const groupAt = panel.indexOf("aria-label={t('research.shareCapital.historyType')}");
        assert.ok(groupAt > -1, 'conmutador con nombre accesible del diccionario');
        const group = panel.slice(groupAt, groupAt + 900);
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
        for (const key of ['fichaViewAll', 'fichaViewAllChanges']) {
            const i = page.indexOf(`              {t('research.${key}')}\n`);
            assert.ok(i > 0, `${key} existe`);
            assert.ok(page.slice(page.lastIndexOf('<Link', i), i).includes(AREA), `${key} con area tactil`);
        }
        const own = readFileSync('components/research/OwnershipSignalsPanel.tsx', 'utf8');
        assert.ok(own.includes(`inline-flex ${AREA} sm:min-h-0 items-center text-sm text-teal-300" href={holdersHref}`), 'Ver propietarios con area tactil');
    });
});

describe('móvil: 44 px en inicio, índice research, watchlist y ProPicks (recorrido 390 px, 31-oct-2026)', () => {
    // Medido en prod con la cuenta de auditoría a 390x844: insignias de ticker
    // de 16 px de alto, chip DCA de 24 px, Filtrar 38 px y paginación 34 px.
    const HIT = "before:absolute before:-inset-2.5 before:content-['']";
    const HIT14 = "before:absolute before:-inset-3.5 before:content-['']";
    it('insignia de ticker de las noticias de inicio: 44 px sin crecer lo visible', () => {
        // 16 px de alto + 14 px por lado (::before -inset-3.5) = 44 px medidos en captura local.
        const src = readFileSync('components/NewsSection.tsx', 'utf8');
        // Feed estilo Quartr (1-nov-2026): el enlace-nombre del ticker lleva el
        // ::before -inset-3.5 (= 44 px de área táctil); el logo es size-12 (48 px).
        assert.ok(src.includes(HIT14), 'enlace del ticker con área táctil invisible de 44 px');
        assert.ok(src.includes('size-12 rounded-xl'), 'logo de empresa de 48 px en la fila');
    });
    it('chip de nivel DCA (watchlist/cartera): visible de 24 px, hit de 44 px', () => {
        const src = readFileSync('components/watchlist/DcaLevelBadge.tsx', 'utf8');
        assert.ok(src.includes(`${HIT} inline-flex min-h-6`), 'chip DCA con área táctil invisible de 44 px');
    });
    it('índice de research: Filtrar y paginación con 44 px en móvil', () => {
        const src = readFileSync('app/(root)/research/page.tsx', 'utf8');
        assert.ok(src.includes('min-h-[44px] rounded-lg border border-gray-700 px-3 py-2'), 'Filtrar con 44 px');
        const pagers = src.match(/inline-flex min-h-\[44px\] items-center rounded-lg border border-gray-700 px-3 py-1\.5/g) ?? [];
        assert.equal(pagers.length, 2, 'Anterior y Siguiente con 44 px');
    });
    it('tira de tickers relacionados: enlaces con 44 px', () => {
        const src = readFileSync('components/research/RelatedTickersStrip.tsx', 'utf8');
        assert.ok(src.includes('inline-flex min-h-[44px] min-w-[44px] items-center font-medium text-gray-200'), 'ticker relacionado con 44 px');
    });
    it('biblioteca: título del documento (tarjeta móvil) con 44 px', () => {
        const src = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
        assert.ok(src.includes('flex min-h-[44px] min-w-0 items-center font-medium text-gray-200'), 'título de documento con 44 px');
    });
    it('inversores: paginación Anterior/Siguiente con 44 px en móvil', () => {
        const src = readFileSync('app/(root)/inversores/_components/Pagination.tsx', 'utf8');
        assert.ok(src.includes('inline-flex min-h-[44px] items-center rounded-lg border border-gray-800'), 'paginación de inversores con 44 px');
    });
    it('calendario de resultados: chips IR y botones de icono con 44 px', () => {
        const src = readFileSync('components/calendar/FollowedEarningsList.tsx', 'utf8');
        assert.ok(src.includes("inline-flex min-h-[44px] items-center gap-1 rounded-md border border-gray-700"), 'chips IR con 44 px');
        const iconos = src.match(/inline-flex h-11 w-11 items-center justify-center rounded-lg/g) ?? [];
        assert.equal(iconos.length, 2, 'fuente y abrir-ficha de 44x44 en móvil');
    });
    it('ProPicks: el conmutador de filtros (solo icono) tiene 44x44', () => {
        const src = readFileSync('components/proPicks/EnhancedProPicksFilters.tsx', 'utf8');
        assert.ok(src.includes('min-h-[44px] min-w-[44px] xl:hidden'), 'conmutador de filtros 44x44');
    });
});
