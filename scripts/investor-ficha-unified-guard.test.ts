import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import vm from 'node:vm';
const read = (path: string) => readFileSync(path, 'utf8');

test('ficha: selector de inversor y contenido propio sin otra barra', () => {
    // ficha por inversor.
    const page = read('app/(root)/inversores/[slug]/page.tsx');
    assert.match(page, /<InvestorSelector investors=\{choices.investors\}/);
    assert.match(page, /<InvestorViewSelector/);
    assert.match(page, /view === "cartas" \? <InvestorLetters/);
    assert.match(page, /view === "videos" \? <InvestorVideos videos=\{investor.videos\}/);
    // #2971 (Nico) añadió a propósito los conceptos al pie de la ficha; lo
    // que sigue prohibido es una segunda barra de navegación.
    assert.doesNotMatch(page, /<nav/);
    assert.match(page, /<InvestorConcepts slug=\{investor.slug\} \/>/);
    const letters = read('app/(root)/inversores/_components/InvestorLetters.tsx');
    assert.match(letters, /paginate\(letters, pagina, 12\)/);
    assert.match(letters, /letter.source_url/);
    assert.match(letters, /letter.publication_date \?\? na/);
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

test('Munger: enlaces del perfil público no son cartas propias', async () => {
    const { execFileSync } = await import('node:child_process');
    const { createRequire } = await import('node:module');
    const require = createRequire(import.meta.url);
    const React = require('react');
    const { renderToStaticMarkup } = require('react-dom/server');
    const publicLetters = JSON.parse(execFileSync('python3', ['-c',
        'import runpy,json; p=runpy.run_path("data-engine/app/services/investor_profiles.py"); print(json.dumps(p["PUBLIC_PROFILES"]["munger"]["letters"]))',
    ], { encoding: 'utf8' }));
    assert.equal(publicLetters.length, 3);
    const code = ts.transpileModule(read('app/(root)/inversores/_components/InvestorLetters.tsx'), {
        compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText;
    const exports: Record<string, (props: object) => unknown> = {};
    vm.runInNewContext(code, { exports, require: (name: string) => {
        if (name === 'next/link') return { default: ({ children, ...props }: { children: unknown }) => React.createElement('a', props, children) };
        if (name === './Pagination') return { paginate: (items: unknown[]) => ({ items, page: 1, total: 1 }), Pagination: () => null };
        if (name === '../cartas/investor-letters') return { investorLetters: () => [] };
        if (name === '@/lib/i18n/server') {
            // Textos en español del diccionario real (la ficha por defecto sale en español).
            const es = JSON.parse(read('lib/i18n/messages/es/investors.json'));
            const t = (key: string) => key.split('.').slice(1).reduce((node: unknown, part: string) => (node as Record<string, unknown> | undefined)?.[part], es) ?? key;
            return { getT: async () => t, getFormat: async () => ({ na: 'N/D' }) };
        }
        return require(name);
    } });
    const html = renderToStaticMarkup(await (exports.InvestorLetters({ slug: 'munger', documents: [], publicLetters }) as Promise<unknown>));
    const sections = html.split('</section>');
    assert.match(sections[0], /N\/D · Sin cartas indexadas/);
    assert.doesNotMatch(sections[0], /Comunicado de Berkshire|Todas las cartas de Berkshire|2023ltr.pdf/);
    assert.match(sections[1], /Fuentes sobre el inversor/);
    for (const source of publicLetters) assert.ok(sections[1].includes(source.url), source.title);
    assert.match(read('app/(root)/inversores/_components/PublicProfile.tsx'), />Fuentes sobre el inversor<\/h2>/);
});
