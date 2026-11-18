/**
 * Auditoría de flujo: las rutas de apoyo y /screeners deben ser alcanzables
 * desde el catálogo compartido (migas, buscador y tarjetas de /discover).
 * Sin catálogo, Breadcrumbs y SectionNav las omitían y /discover no pintaba
 * la tarjeta de Screeners aunque la página existía.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types.
import { buildCrumbs } from '../lib/nav/build-crumbs.ts';
// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types.
import { flattenNavItems, NAV_SECTIONS } from '../lib/constants.ts';

const SUPPORT_ROUTES = [
  ['/export', 'nav.items.export'],
  ['/settings', 'shell.user.settings'],
  ['/security', 'shell.user.security'],
] as const;

const catalogItem = (href: string) => flattenNavItems().find((item) => item.href === href);

void test('/export, /settings y /security están en el catálogo, sin hub y fuera del menú lateral', () => {
  const sidebarHrefs = NAV_SECTIONS.flatMap((section) => section.items.map((item) => item.href));
  for (const [href, labelKey] of SUPPORT_ROUTES) {
    const item = catalogItem(href);
    assert.ok(item, `${href} debe estar en ROUTE_CATALOG`);
    assert.equal(item?.hub, null, `${href} no debe resaltar ningún hub`);
    assert.equal(item?.labelKey, labelKey);
    assert.ok(!sidebarHrefs.includes(href), `${href} no debe entrar en NAV_SECTIONS`);
  }
});

void test('las rutas de apoyo generan migas legibles en la sección Sistema', () => {
  for (const [href, labelKey] of SUPPORT_ROUTES) {
    const crumbs = buildCrumbs(href);
    assert.deepEqual(crumbs.map((crumb) => crumb.labelKey), ['nav.items.inicio', 'nav.sections.sistema', labelKey]);
    assert.equal(crumbs[crumbs.length - 1].href, href);
  }
});

void test('/screeners vuelve a mostrar tarjeta en el hub /discover', () => {
  const item = catalogItem('/screeners');
  assert.equal(item?.descriptionKey, 'nav.descriptions.screeners');
  const tools = flattenNavItems().filter(
    (node) => node.hub === '/discover' && node.href !== '/discover' && node.descriptionKey,
  );
  assert.ok(tools.some((node) => node.href === '/screeners'), '/screeners debe aparecer entre las tarjetas');
});
