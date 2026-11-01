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
    const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).thesisDoc;
    it('el estado se muestra traducido, nunca en crudo («draft»)', () => {
        assert.ok(!tesis.includes('«${latest.status}»'), 'no se interpola el status crudo');
        assert.match(tesis, /draft: 'borrador'/, 'mapa de estados con draft traducido');
        assert.ok(tesis.includes('statusLabel(latest.status, t, locale)'), 'la descripcion usa statusLabel');
    });
    it('el estado vacio ofrece volver a la ficha (no es un callejon)', () => {
        assert.ok(tesis.includes('EmptyLink'), 'usa EmptyLink');
        assert.ok(tesis.includes("?view=thesis`}>{t('research.thesisDoc.reviewVersion'") && es.reviewVersion.startsWith('Revisar la v'), 'accion al borrador en la ficha');
    });
    it('una version datos insuficientes se lee como PROVISIONAL rotulada, nunca vacia (Nico HYMC, 2026-10-21)', () => {
        assert.ok(tesis.includes("latest.status === 'insufficient_data'"), 'rama provisional solo para datos insuficientes (sin cifras por construccion)');
        assert.ok(tesis.includes("t('research.thesisDoc.provisionalBadge')") && es.provisionalBadge === 'PROVISIONAL — no publicada', 'badge provisional explicito');
        assert.ok(tesis.includes('/pdf?draft=1'), 'PDF del borrador por la ruta draft existente (lista blanca backend, sin cifras)');
        assert.ok(tesis.includes("t('research.thesisDoc.draftNoFigures')") && es.draftNoFigures.startsWith('Sin cifras de valoración en esta vista'), 'declara la ausencia de valoracion con causa, sin tabla de escenarios');
        // Rechazada/sustituida/obsoleta/borrador CON cifras: caen al estado
        // vacio honesto con salida a la ficha; nunca se presentan como
        // provisional valida.
        assert.ok(tesis.indexOf("latest.status === 'insufficient_data'") < tesis.indexOf('!published ? ('), 'el resto de estados sigue al estado vacio');
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

describe('QA ficha: navegación sin scrollbar ni niveles extra (10, revisado 29-oct-2026)', () => {
    it('una sola fila de seis pestañas; sin barra de módulos', () => {
        const nav = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');
        // Seis pestañas a un toque alimentadas por TABS; en móvil la fila se
        // desliza (scroll nativo) y en desktop sobra sitio: nada de una
        // segunda barra de módulos que desbordaba a 1280px.
        assert.ok(nav.includes('TABS.map'), 'la fila sale del mapa de pestañas');
        assert.ok(nav.includes('overflow-x-auto'), 'la fila se desliza en móvil');
        assert.ok(!nav.includes('Módulos de'), 'sin barra de módulos: son secciones ancladas');
    });
});
