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
 for(const [page,key,title] of [['discover','discover.metaTitle','Descubrir'],['research/sources','research.sourcesMetaTitle','Fuentes']]) { assert.ok(read(`app/(root)/${page}/page.tsx`).includes(`title: t('${key}')`)); const [ns, leaf] = key.split('.'); assert.equal(JSON.parse(read(`lib/i18n/messages/es/${ns}.json`))[leaf], title); }
 // security migro a generateMetadata + t(): clave en la pagina y ES del dict == literal historico.
 assert.ok(read('app/(root)/security/page.tsx').includes("title: t('security.page.metaTitle')"));
 assert.equal(JSON.parse(read('lib/i18n/messages/es/security.json')).page.metaTitle, 'Seguridad');
 // research/news migro a generateMetadata + t(): clave en la pagina y ES del dict == literal historico.
 assert.ok(read('app/(root)/research/news/page.tsx').includes("title: t('research.newsMetaTitle')"));
 assert.equal(JSON.parse(read('lib/i18n/messages/es/research.json')).newsMetaTitle, 'Noticias');
 assert.match(read('app/(root)/inversores/[slug]/page.tsx'),/investor.name/);
 const missing=read('app/not-found.tsx');
 assert.match(missing,/<header/);assert.match(missing,/aria-label=\{t\('errors\.notFound\.navAria'\)\}/);
 const esErrors404 = JSON.parse(read('lib/i18n/messages/es/errors.json'));
 assert.equal(esErrors404.notFound.navAria, 'Navegación principal');
 assert.equal(esErrors404.notFound.metaTitle, 'Página no encontrada');
 assert.ok(missing.includes("t('errors.notFound.metaTitle')"));
});
test('ticker targets and removal names are usable without icons',()=>{
 assert.match(read('components/watchlist/WatchlistRemoveButton.tsx'),/aria-label=\{t\('watchlist\.remove\.label', \{ symbol \}\)\}/);
 assert.equal(JSON.parse(read('lib/i18n/messages/es/watchlist.json')).remove.label,'Quitar {symbol} de la watchlist');
 assert.match(read('app/(root)/watchlist/page.tsx'),/min-h-11 items-center truncate text-base/);
 const news=read('components/research/NewsEventsFlow.tsx');
 assert.ok((news.match(/inline-flex min-h-11[^"]*items-center[^"]*text-teal-300/g)??[]).length>=2);
});
