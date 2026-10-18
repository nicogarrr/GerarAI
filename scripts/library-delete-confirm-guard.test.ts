import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
test('library delete uses authenticated existing route and confirmation in both layouts',()=>{
 const page=readFileSync('app/(root)/knowledge/page.tsx','utf8');
 assert.equal((page.match(/confirmMessage=\{`¿Eliminar el documento/g)||[]).length,2);
 assert.match(readFileSync('lib/actions/research-tools.actions.ts','utf8'),/deleteKnowledgeDocument[\s\S]*method: 'DELETE'/);
 const form=readFileSync('components/forms/MutationForm.tsx','utf8');
 assert.ok(form.indexOf('window.confirm')<form.indexOf('await action(formData)'));
});
test('library refresh is active-job scoped and cleaned up; completion feedback remains',()=>{
 const page=readFileSync('app/(root)/knowledge/page.tsx','utf8');
 assert.match(page,/ExtractionRefresh active=\{activeJobs.length > 0\}/);
 assert.match(page,/extractionResultText\(job\)/);
 const refresh=readFileSync('components/knowledge/ExtractionRefresh.tsx','utf8');
 assert.match(refresh,/if\(!active\) return/);assert.match(refresh,/clearInterval/);
});
