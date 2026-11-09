import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const read=(p:string)=>readFileSync(p,'utf8');
test('search restores focus via dialog close-autofocus to connected opener',()=>{
 const search=read('components/SearchCommand.tsx')+read('components/SearchCommandDialog.tsx');
 assert.match(search,/returnFocusRef\.current\?\.isConnected/);
 assert.match(search,/onCloseAutoFocus=/);
 assert.match(search,/getFocusTarget\(\)\?\.focus\(\)/);
 assert.match(read('components/ui/command.tsx'),/onCloseAutoFocus=\{onCloseAutoFocus\}/);
});
test('page titles and 404 navigation are explicit and human readable',()=>{
 // La clave puede ir inline (`title: t('...')`) o via i18nPageTitle (#5067); la
 // via helper solo vale si su contrato (getT -> { title: t(key) }) sigue vivo,
 // y la clave debe existir en es Y en: no se permite omitir la traduccion.
 const metaHelper=read('lib/i18n/metadata.ts');
 const helperTraduce=metaHelper.includes('const t = await getT();')&&metaHelper.includes('return { title: t(titleKey) };');
 const hasTitleKey=(src:string,key:string)=>src.includes(`title: t('${key}')`)||(helperTraduce&&src.includes(`i18nPageTitle('${key}')`));
 const enHas=(ns:string,path:string[])=>{let node=JSON.parse(read(`lib/i18n/messages/en/${ns}.json`));for(const p of path)node=node?.[p];return typeof node==='string'&&node.length>0;};
 for(const [page,key,title] of [['discover','discover.metaTitle','Descubrir'],['research/sources','research.sourcesMetaTitle','Fuentes']]) { assert.ok(hasTitleKey(read(`app/(root)/${page}/page.tsx`),key)); const [ns, leaf] = key.split('.'); assert.equal(JSON.parse(read(`lib/i18n/messages/es/${ns}.json`))[leaf], title); assert.ok(enHas(ns,[leaf]),`${key} debe existir tambien en en`); }
 // security migro a generateMetadata + t(): clave en la pagina y ES del dict == literal historico.
 assert.ok(hasTitleKey(read('app/(root)/security/page.tsx'),'security.page.metaTitle'));
 assert.equal(JSON.parse(read('lib/i18n/messages/es/security.json')).page.metaTitle, 'Seguridad');
 assert.ok(enHas('security',['page','metaTitle']),'security.page.metaTitle debe existir tambien en en');
 // research/news migro a generateMetadata + t(): clave en la pagina y ES del dict == literal historico.
 assert.ok(hasTitleKey(read('app/(root)/research/news/page.tsx'),'research.newsMetaTitle'));
 assert.equal(JSON.parse(read('lib/i18n/messages/es/research.json')).newsMetaTitle, 'Noticias');
 assert.ok(enHas('research',['newsMetaTitle']),'research.newsMetaTitle debe existir tambien en en');
 assert.match(read('app/(root)/inversores/[slug]/page.tsx'),/investor.name/);
 const missing=read('app/not-found.tsx');
 assert.match(missing,/<header/);assert.match(missing,/aria-label=\{t\('errors\.notFound\.navAria'\)\}/);
 const esErrors404 = JSON.parse(read('lib/i18n/messages/es/errors.json'));
 assert.equal(esErrors404.notFound.navAria, 'Navegación principal');
 assert.equal(esErrors404.notFound.metaTitle, 'Página no encontrada');
 assert.ok(missing.includes("t('errors.notFound.metaTitle')")||(helperTraduce&&missing.includes("i18nPageTitle('errors.notFound.metaTitle')")));
 assert.ok(enHas('errors',['notFound','metaTitle']),'errors.notFound.metaTitle debe existir tambien en en');
});
test('ticker targets and removal names are usable without icons',()=>{
 assert.match(read('components/watchlist/WatchlistRemoveButton.tsx'),/aria-label=\{t\('watchlist\.remove\.label', \{ symbol \}\)\}/);
 assert.equal(JSON.parse(read('lib/i18n/messages/es/watchlist.json')).remove.label,'Quitar {symbol} de la watchlist');
 assert.match(read('app/(root)/watchlist/page.tsx'),/min-h-11 items-center truncate text-base/);
 const news=read('components/research/NewsEventsFlow.tsx');
 assert.ok((news.match(/inline-flex min-h-11[^"]*items-center[^"]*text-teal-300/g)??[]).length>=2);
});
