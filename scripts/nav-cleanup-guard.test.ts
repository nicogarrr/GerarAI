/**
 * Quick win UX 3: nav limpio. Sin duplicados Plan/Mi plan ni Ayuda x2, sin
 * /research/workflows en el árbol principal y «Vista de mercado» renombrada
 * a «Mercado».
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const constants = readFileSync('lib/constants.ts', 'utf8');
const sidebar = readFileSync('components/layout/Sidebar.tsx', 'utf8');
const breadcrumbs = readFileSync('components/layout/Breadcrumbs.tsx', 'utf8');

test('cada destino del sidebar aparece una sola vez (árbol + pie)', () => {
    // /plan y /help tenían entrada en NAV_SECTIONS Y en el pie del sidebar.
    assert.ok(!sidebar.includes('FooterLink href="/plan"'), '/plan duplicado en el pie del sidebar');
    assert.ok(!sidebar.includes('FooterLink href="/help"'), '/help duplicado en el pie del sidebar');
    // /security no está en el árbol: su pie se mantiene.
    assert.ok(!sidebar.includes('FooterLink href="/security"'));
    assert.ok(readFileSync("components/UserDropdown.tsx", "utf8").includes('router.push("/security")'));
    // En el árbol, cada href una vez.
    const tree = constants.slice(constants.indexOf('export const NAV_SECTIONS'), constants.indexOf('export function flattenNavItems'));
    assert.ok(!tree.includes("href: '/export'"), '/export ya no esta en el menu');
    for (const href of ['/plan', '/help']) {
        const occurrences = tree.split(`href: '${href}'`).length - 1;
        assert.equal(occurrences, 1, `${href} debe aparecer exactamente una vez en NAV_SECTIONS`);
    }
});

test('la sección del plan tiene un solo destino: sin título duplicado', () => {
    // «Mi plan» con un solo item no muestra título (showsNavSectionTitle) y
    // el nav deja de leer «Mi plan / Plan» seguidos.
    const section = /title: 'Mi plan',\s*\n\s*items: \[([\s\S]*?)\],\s*\n\s*\}/.exec(constants);
    assert.ok(section, 'sección Mi plan no encontrada');
    assert.equal((section[1].match(/href:/g) ?? []).length, 1);
    assert.match(constants, /export function showsNavSectionTitle[\s\S]*?section\.items\.length > 1/);
});

test('/research/workflows eliminado (pagina sin uso)', () => {
    assert.ok(!constants.includes('/research/workflows'), 'Workflows no debe estar en la navegacion');
    assert.ok(!breadcrumbs.includes("'workflows'"));
});

test('«Vista de mercado» pasa a «Mercado»', () => {
    assert.ok(!constants.includes('Vista de mercado'), 'queda el nombre antiguo');
    assert.match(constants, /\{ href: '\/screener', label: 'Mercado', icon: LineChart, hub: '\/discover'/);
});

test('el árbol del sidebar encoge con min-h-0: el pie queda alcanzable', () => {
    // Sin min-h-0 en un flex-col, el nav no encoge por debajo de su
    // contenido: el aside supera h-dvh y el pie (Seguridad) cae bajo el
    // fold sin scroll interno en viewports bajos.
    const sidebar = readFileSync('components/layout/Sidebar.tsx', 'utf8');
    assert.match(sidebar, /min-h-0 flex-1 overflow-y-auto/);
});

test('el alto del aside descuenta la zona pegajosa (h-dvh a secas destierra el pie)', () => {
    // Con h-dvh y top-0 el aside mide el viewport entero empezando debajo
    // del header a scroll 0: sus ultimos --shell-top px caen bajo el fold.
    // El alto correcto es 100dvh - --shell-top anclado a top: --shell-top.
    assert.match(sidebar, /top-\[var\(--shell-top\)\]/);
    assert.match(sidebar, /h-\[calc\(100dvh-var\(--shell-top\)\)\]/);
});

/**
 * Coherencia real de navegación (auditoría 17-oct): antes este guard pasaba
 * mientras /temas, /cuellos, /macro-calendar, /portfolio/stress y
 * /research/assistant no estaban en NINGUNA lista (sin miga legible, sin
 * buscador) y /alerts y /export no resaltaban ninguna sección. Estas pruebas
 * cruzan el filesystem con el ROUTE_CATALOG para que una ruta nueva sin
 * catalogar (o una entrada del catálogo sin página) rompa CI.
 */
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const catalogBlock = constants.slice(
    constants.indexOf('export const ROUTE_CATALOG'),
    constants.indexOf('export const MOBILE_TAB_ITEMS'),
);
const catalogHrefs = [...catalogBlock.matchAll(/href: '([^']+)'/g)].map((m) => m[1]);

function listRoutes(dir: string, base: string): string[] {
    const routes: string[] = [];
    if (existsSync(join(dir, 'page.tsx'))) routes.push(base || '/');
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) routes.push(...listRoutes(full, `${base}/${entry}`));
    }
    return routes;
}

// Rutas reales fuera del catálogo A PROPÓSITO. Cada una lleva su motivo; una
// ruta nueva que no esté en el catálogo ni aquí rompe el guard.
const CATALOG_EXCEPTIONS: Record<string, string> = {
    '/security': 'menú del avatar (UserDropdown), no es destino de sección',
    '/settings': 'menú del avatar (UserDropdown), no es destino de sección',
    // '/research/data-health' se eliminó entera por decisión de Nico (2026-10-20).
    '/export': 'quitado del menú por decisión de Nico (sin uso); ruta conservada y enlazada desde Ayuda',
    '/search': 'página-herramienta del buscador global, se abre desde el header',
    // /inversores/mas-compradas y /inversores/solape ya no existen: son
    // vistas de /ownership (decision de Nico, WhatsApp 2026-10-20 00:59).
    // Subpáginas del módulo Inversores: las cubre su HubNav propio
    // (app/(root)/inversores/layout.tsx) y las migas las nombran vía
    // SUBROUTE_LABELS/humanizeSlug.
    '/inversores/aprender': 'subnav propio de Inversores (HubNav); índice de Aprender (Opción A, decisión de Nico 2026-10-20)',
    '/inversores/cartas': 'subnav propio de Inversores (HubNav)',
    '/inversores/videos': 'subnav propio de Inversores (HubNav)',
    '/inversores/conceptos': 'subnav propio de Inversores (HubNav)',
    // El asistente de research se unificó en el Cerebro: la ruta queda solo
    // como redirect que lo abre (handoff sessionStorage + evento open-brain).
    '/calendar/resultados': 'pestaña de CalendarTabs (subnav propio de Calendarios)',
    '/calendar/suscripcion': 'pestaña de CalendarTabs (subnav propio de Calendarios)',
    '/research/assistant': 'redirect de compatibilidad al Cerebro (asistente unificado)',
};

const HUBS = new Set(['/inicio', '/portfolio', '/research', '/discover', '/watchlist', '/knowledge']);

test('toda ruta estática de app/(root) está en el ROUTE_CATALOG o excepción documentada', () => {
    const routes = listRoutes('app/(root)', '')
        .filter((route) => !route.includes('[')) // dinámicas: las cubre el ancla por prefijo
        .filter((route) => route !== '/');
    const catalog = new Set(catalogHrefs);
    const missing = routes.filter((route) => !catalog.has(route) && !(route in CATALOG_EXCEPTIONS));
    assert.deepEqual(missing, [], `rutas sin catalogar ni excepción: ${missing.join(', ')}`);
});

test('todo href del ROUTE_CATALOG existe como página (root o pública)', () => {
    const missing = catalogHrefs.filter(
        (href) =>
            !existsSync(join('app/(root)', href, 'page.tsx')) &&
            !existsSync(join('app/(public)', href, 'page.tsx')),
    );
    assert.deepEqual(missing, [], `entradas del catálogo sin página: ${missing.join(', ')}`);
});

test('ningún href se repite en el ROUTE_CATALOG', () => {
    const seen = new Set<string>();
    const dupes = catalogHrefs.filter((href) => (seen.has(href) ? true : (seen.add(href), false)));
    assert.deepEqual(dupes, []);
});

test('cada item del catálogo declara su hub y es uno de los 6 hubs o null', () => {
    const itemCount = (catalogBlock.match(/href: '/g) ?? []).length;
    const hubDecls = [...catalogBlock.matchAll(/hub: (null|'[^']+')/g)].map((m) => m[1]);
    assert.equal(hubDecls.length, itemCount, 'cada item declara hub exactamente una vez');
    for (const hub of hubDecls) {
        if (hub === 'null') continue;
        assert.ok(HUBS.has(hub.replaceAll("'", '')), `hub desconocido: ${hub}`);
    }
});

test('sectionForRoute se deriva del catálogo: sin listas de rutas paralelas', () => {
    const fn = constants.slice(
        constants.indexOf('export function sectionForRoute'),
        constants.indexOf('export function showsNavSectionTitle'),
    );
    assert.match(fn, /flattenNavItems\(\)/);
    assert.ok(!fn.includes("'/"), 'sectionForRoute no debe listar rutas a mano');
});

test('SectionNav se deriva del catálogo y cede en el hub fusionado Inversores/Señales', () => {
    const nav = readFileSync('components/layout/SectionNav.tsx', 'utf8');
    assert.match(nav, /flattenNavItems/);
    // Decision de Nico (WhatsApp 2026-10-20 00:59): /inversores, /insider y
    // /ownership comparten el HubNav del hub fusionado (4 pestañas), asi que
    // SectionNav se excluye ahi por ruta. Revierte la mitad de #1924 (doble
    // barra): una sola barra, la del hub. /inversores/canales sigue fuera
    // porque pertenece al hub Biblioteca.
    const literals = [...nav.matchAll(/'(\/[^']*)'/g)].map((m) => m[1]).filter((l) => l.startsWith('/'));
    // Calendarios (/calendar, /macro-calendar, /corporate-actions) tambien se
    // excluyen: CalendarTabs es su unica barra, con «Cartera» de primera pestaña
    // (opcion B, WhatsApp 2026-10-28 08:46).
    assert.deepEqual([...new Set(literals)].sort(), [
        '/calendar',
        '/corporate-actions',
        '/discover',
        '/insider',
        '/insider/',
        '/inversores',
        '/inversores/',
        '/inversores/canales',
        '/macro-calendar',
        '/ownership',
        '/ownership/',
    ]);
    // El HubNav compartido SI incluye 13F e Insiders: es la barra del hub fusionado.
    const hub = readFileSync('app/(root)/inversores/_components/HubNav.tsx', 'utf8');
    assert.ok(hub.includes('"/ownership"') && hub.includes('"/insider"'));
    assert.ok(!hub.includes('lime-'));
});

test('/discover se deriva del catálogo: sin lista de tarjetas paralela', () => {
    const page = readFileSync('app/(root)/discover/page.tsx', 'utf8');
    assert.match(page, /flattenNavItems/);
    assert.ok(!page.includes("href:'/"), 'sin tools hardcodeados en /discover');
});
