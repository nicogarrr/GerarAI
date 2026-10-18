import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
// @ts-expect-error explicit extension for node
import {extractionResultText,noPrinciplesText} from '../lib/knowledge/job-feedback.ts';
test('failed extraction does not leak provider diagnostics in rows or empty states',()=>{
 const job={status:'failed',result:{},error:'ProviderTransportError: opencode-go transport failed: timeout after 1 attempt(s)'};
 assert.equal(extractionResultText(job),'La extracción tardó demasiado. Vuelve a intentarlo.');
 assert.equal(noPrinciplesText([job]),extractionResultText(job));
 for(const error of ['stacktrace secret raw','RateLimit 429','']){
  const output=extractionResultText({...job,error});
  assert.ok(output && !output.includes('stacktrace') && !output.includes('429'));
 }
});
test('library omits absent publication date and reserves desktop FAB rail',()=>{
 const s=readFileSync('app/(root)/knowledge/page.tsx','utf8');
 assert.ok(s.includes('overflow-x-clip md:pr-20'));
 assert.ok(s.includes('document.publication_date && formatDate'));
 assert.ok(!s.includes("'Autor desconocido'} · {formatDate"));
});
