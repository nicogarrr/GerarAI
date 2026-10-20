import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import vm from 'node:vm';
const read = (path: string) => readFileSync(path, 'utf8');

test('ficha: selector de inversor y contenido propio sin otra barra', () => {
    // Nico, WhatsApp 2026-10-20 08:30:56: ficha por inversor.
    const page = read('app/(root)/inversores/[slug]/page.tsx');
    assert.match(page, /<InvestorSelector investors=\{choices.investors\}/);
    assert.match(page, /<InvestorViewSelector/);
    assert.match(page, /view === "cartas" \? <InvestorLetters/);
    assert.match(page, /view === "videos" \? <InvestorVideos videos=\{investor.videos\}/);
    assert.doesNotMatch(page, /<nav|<InvestorConcepts/);
    const letters = read('app/(root)/inversores/_components/InvestorLetters.tsx');
    assert.match(letters, /paginate\(letters, pagina, 12\)/);
    assert.match(letters, /letter.source_url/);
    assert.match(letters, /letter.publication_date \?\? "N\/D"/);
    assert.match(letters, /publicLetters.map/);
    assert.doesNotMatch(letters, /slice\(0, 4\)/);
});

test('cartas: nunca mezcla un autor distinto ni documentos sin preparar', () => {
    const base = { document_type: 'fund_letter', status: 'ready', publication_date: null, source_url: null };
    const docs = [
        { ...base, id: 1, title: 'Berkshire', author: 'Warren Buffett' },
        { ...base, id: 2, title: 'Daily Journal', author: 'Charlie Munger' },
        { ...base, id: 3, title: 'Incompleta', author: 'Warren Buffett', status: 'failed' },
    ];
    const source = read('app/(root)/inversores/cartas/investor-letters.ts');
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
    const exports: Record<string, (slug: string, docs: typeof base[]) => { id: number }[]> = {};
    vm.runInNewContext(compiled, { exports, require: () => ({ authorKey: (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-') }) });
    assert.equal(JSON.stringify(exports.investorLetters('buffett', docs).map((doc) => doc.id)), '[1]');
    assert.equal(JSON.stringify(exports.investorLetters('munger', docs).map((doc) => doc.id)), '[2]');
    assert.equal(JSON.stringify(exports.investorLetters('desconocido', docs)), '[]');
});

test('Aprender conserva solo Conceptos y Canales; lectores viejos siguen accesibles', () => {
    const page = read('app/(root)/inversores/aprender/page.tsx');
    assert.doesNotMatch(page, /href: '\/inversores\/(cartas|videos)'/);
    assert.match(page, /href: '\/inversores\/conceptos'/);
    assert.match(page, /href: '\/inversores\/canales'/);
    assert.match(read('app/(root)/inversores/cartas/[id]/page.tsx'), /investorLetters\(inversor, \[letter\]\)/);
});
