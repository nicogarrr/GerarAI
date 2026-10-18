import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
test('manual source choice is validated and only transcript calls transcript import', () => {
 const source = readFileSync('lib/actions/research.actions.ts','utf8');
 const action = source.slice(source.indexOf('export async function importResearchSource'), source.indexOf('export async function importResearchDocumentFile'));
 assert.match(action, /\['manual_upload', 'manual_transcript', 'company_ir'\]\.includes/);
 assert.match(action, /if \(sourceType === 'manual_transcript'\)/);
 assert.match(action, /new File\(\[text\], 'manual-source.txt'/);
 assert.match(action, /payload.set\('source_type', sourceType\)/);
});
test('upload result includes confirmed ticker and ID with persistent feedback opt in', () => {
 const source = readFileSync('lib/actions/research.actions.ts','utf8');
 assert.match(source, /Documento ya existente/);
 assert.match(source, /result.ticker.*result.document_id/);
 const page = readFileSync('app/(root)/research/sources/page.tsx','utf8');
 assert.match(page, /id="manual-source-type"/);
 assert.equal((page.match(/showSuccessInline/g)||[]).length, 3);
 const form = readFileSync('components/forms/MutationForm.tsx','utf8');
 assert.match(form, /if \(showSuccessInline\) setSuccess\(message\)/);
 assert.match(form, /role="status">\{success\}/);
});
