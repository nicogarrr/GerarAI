import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
test('external translation preserves linked original and uses authenticated signed backend',()=>{
 const ui=readFileSync('components/research/ExternalNewsHeadline.tsx','utf8');
 for(const text of ["research.translate.autoViewOriginal",'text ?? headline','href={url}','IntersectionObserver','translate-headline','isTranslatable',"research.translate.originalHeadline"]) assert.ok(ui.includes(text));
 // Copy por clave i18n: en español sigue siendo el mismo texto.
 const es=JSON.parse(readFileSync('lib/i18n/messages/es/research.json','utf8')).translate;
 assert.equal(es.originalHeadline,'Titular original (sin traducir)');
 assert.equal(es.autoViewOriginal,'Traducción automática · ver original');
 // Con el inglés elegido no se traduce al español.
 assert.ok(ui.includes("const canTranslate = !english &&"));
 assert.ok(!ui.includes('tail = job'), 'la cola serie de 1 queda sustituida por la cola con concurrencia 2');
 const route=readFileSync('app/api/news/translate-headline/route.ts','utf8');
 assert.ok(route.includes('requireAuthenticatedUser'));
 const proxy=readFileSync('lib/research/post-proxy.ts','utf8');
 assert.ok(route.includes('proxyResearchPost'), 'la mecánica del POST firmado vive en el helper compartido');
 assert.ok(proxy.includes("researchIdentityHeaders({method:'POST',path,body})"));
});
test('dashboard badges are in their own row, not over headlines',()=>{
 const s=readFileSync('components/NewsSection.tsx','utf8');
 assert.ok(s.includes('ExternalNewsHeadline'));
 assert.ok(!s.includes('absolute right-3 top-3'));
 assert.ok(!s.includes('line-clamp-2 group-hover'));
});
