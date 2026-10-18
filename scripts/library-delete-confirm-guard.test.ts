import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
test('library refresh is active-job scoped and cleaned up; completion feedback remains',()=>{
 const page=readFileSync('app/(root)/knowledge/page.tsx','utf8');
 assert.match(page,/ExtractionRefresh active=\{activeJobs.length > 0\}/);
 assert.match(page,/extractionResultText\(job\)/);
 const refresh=readFileSync('components/knowledge/ExtractionRefresh.tsx','utf8');
 assert.match(refresh,/if\(!active\) return/);assert.match(refresh,/clearInterval/);
});
