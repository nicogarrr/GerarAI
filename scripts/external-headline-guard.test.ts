import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
test('external translation preserves linked original and uses authenticated signed backend',()=>{
 const ui=readFileSync('components/research/ExternalNewsHeadline.tsx','utf8');
 for(const text of ['ver original','text ?? headline','href={url}','IntersectionObserver','translate-headline','isTranslatable','Titular original (sin traducir)']) assert.ok(ui.includes(text));
 assert.ok(!ui.includes('tail = job'), 'la cola serie de 1 queda sustituida por la cola con concurrencia 2');
 const route=readFileSync('app/api/news/translate-headline/route.ts','utf8');
 assert.ok(route.includes('requireAuthenticatedUser'));
 assert.ok(route.includes("researchIdentityHeaders({method:'POST',path,body})"));
});
test('dashboard badges are in their own row, not over headlines',()=>{
 const s=readFileSync('components/NewsSection.tsx','utf8');
 assert.ok(s.includes('ExternalNewsHeadline'));
 assert.ok(!s.includes('absolute right-3 top-3'));
 assert.ok(!s.includes('line-clamp-2 group-hover'));
});
