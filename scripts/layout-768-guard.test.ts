import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tabs = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');
const landing = readFileSync('components/landing/PublicLanding.tsx', 'utf8');

test('F289: el texto del banner de /portfolio salta a su propia fila antes de colapsar', () => {
    // flex-1 sin basis dejaba al <p> con ~50px en 768px (sidebar + dos enlaces):
    // con basis-60 el navegador lo envuelve a una fila completa por debajo de
    // 240px en vez de comprimirlo. (El copy pasó a subtítulo de una línea en
    // el quick win UX 2; las clases de layout que importan son las mismas.)
    assert.match(tabs, /<p className="min-w-0 flex-1 basis-60 text-sm font-medium text-gray-300">/);
});

test('F285: los CTAs del hero envuelven en sm en vez de desbordar a 768px', () => {
    // Los Button llevan whitespace-nowrap + shrink-0: en una fila sm sin wrap
    // la suma supera 768px (scrollWidth 847). flex-wrap manda el segundo CTA
    // a la siguiente línea.
    const heroActions = landing.match(/<div className="([^"]*)">\s*\{signUpOpen \?/);
    assert.ok(heroActions, 'Debe existir el contenedor de CTAs del hero');
    const classes = new Set(heroActions[1].split(/\s+/));
    for (const token of ['flex', 'flex-col', 'sm:flex-row', 'sm:flex-wrap']) {
        assert.ok(classes.has(token), `El contenedor de CTAs necesita ${token}`);
    }
});

const modelPanels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
const researchPage = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('F319: la pista del grid de escenarios puede encoger para que la tabla haga scroll interno', () => {
    // Sin min-w-0 en la pista, el min-content de la tabla (min-w-[540px])
    // expandía el grid por encima del contenedor entre 768 y 1279px en vez
    // de dejar que el wrapper overflow-x-auto recortara.
    assert.match(modelPanels, /lg:grid-cols-\[1\.2fr_0\.8fr\]">[\s\S]{0,900}<div className="min-w-0">/);
    assert.match(modelPanels, /aria-label=\{ti\('research\.model\.scenariosLabel'\)\} className="hidden overflow-x-auto md:block"/);
    // F27: la pista de escenarios solo se renderiza si el modelo es publicable
    // (sin WACC publicable no se muestran escenarios; regla de Nico 2026-10-16).
    assert.match(modelPanels, /\{model\.publishable \? \(/);
});

test('F320: el nombre de métrica irrompible no empuja el badge fuera de la tarjeta a 768px', () => {
    // net_debt_to_ebitda es un token largo sin puntos de corte: min-w-0 +
    // break-all dejan que envuelva y shrink-0 protege el badge de estado.
    assert.match(researchPage, /min-w-0 break-all font-medium text-gray-200">\{metricLabel\(metric\.metric, locale\)\}<\/span>/);
    assert.match(researchPage, /<Badge className="shrink-0" variant="outline">\{label\(metric\.status, locale\)\}<\/Badge>/);
});

test('F290: los KPIs de /portfolio dimensionan por ancho de contenido (sidebar en md)', () => {
    // grid-cols-2 md:grid-cols-4 asumía viewport≈contenido: con el sidebar de
    // 15rem visible desde md, a 768px el contenido son ~31rem y 4 columnas
    // dejaban ~7rem por tarjeta (valores clipados, 4ª fuera del borde).
    // auto-fit+minmax(12rem) colapsa a 2 columnas hasta que cada tarjeta
    // tiene sitio real (~1280px con sidebar), sin tocar el móvil (<sm sigue
    // en 2 columnas, verificado por QA).
    const summary = readFileSync('components/portfolio/PortfolioSummary.tsx', 'utf8');
    assert.match(summary, /grid grid-cols-2 gap-3 sm:gap-4 sm:\[grid-template-columns:repeat\(auto-fit,minmax\(12rem,1fr\)\)\]/);
    assert.doesNotMatch(summary, /md:grid-cols-4/);});
