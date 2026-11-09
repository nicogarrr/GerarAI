import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
const source=(p:string)=>readFileSync(p,'utf8');
test('six primary destinations, contextual tools and a global alerts link',()=>{
 const s=source('lib/constants.ts');
 const primary=s.slice(s.indexOf('export const NAV_SECTIONS'),s.indexOf('export const ROUTE_CATALOG'));
 assert.equal((primary.match(/href:/g)??[]).length,6);
 for(const href of ['/inicio','/portfolio','/research','/discover','/watchlist','/knowledge'])assert.ok(primary.includes(`href: '${href}'`));
 assert.ok(source('components/Header.tsx').includes("aria-label={t('shell.header.alerts')}"));
 assert.equal(JSON.parse(source('lib/i18n/messages/es/shell.json')).header.alerts,'Alertas');
 assert.ok(source('app/(root)/layout.tsx').includes('<SectionNav />'));
 assert.ok(!source('components/layout/Sidebar.tsx').includes('FooterLink href="/security"'));
 // La clave puede ir inline o via i18nPageTitle (#5067); si va via helper, su
 // contrato (getT -> { title: t(key) }) queda fijado aqui: sin el, el helper
 // podria dejar de traducir sin que ninguna guarda lo note.
 const discoverPage=source('app/(root)/discover/page.tsx');
 const metaHelper=source('lib/i18n/metadata.ts');
 const helperTraduce=metaHelper.includes('const t = await getT();')&&metaHelper.includes('return { title: t(titleKey) };');
 const discoverInline=discoverPage.includes("t('discover.metaTitle')");
 const discoverHelper=helperTraduce&&discoverPage.includes("i18nPageTitle('discover.metaTitle')");
 assert.ok((discoverInline||discoverHelper) && source('lib/i18n/messages/es/discover.json').includes('"Descubrir"'));
 assert.ok(JSON.parse(source('lib/i18n/messages/en/discover.json')).metaTitle,'discover.metaTitle debe existir tambien en en');
});
