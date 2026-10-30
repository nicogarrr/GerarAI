import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const source = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
const bibliotecaTab = source.slice(source.indexOf('<TabsContent className="mt-2 space-y-6" value={TABS.biblioteca}>'), source.indexOf('<TabsContent className="mt-2" value={TABS.subir}>'));
const subirTab = source.slice(source.indexOf('<TabsContent className="mt-2" value={TABS.subir}>'), source.indexOf('<TabsContent className="mt-2" value={TABS.principios}>'));

// Biblioteca (UX 30-oct): «Fragmentos» llevaba a /knowledge?document=N y el
// explorador se pintaba al final de la pestaña, tras cifras, colecciones,
// dos formularios y la lista entera: en móvil el enlace parecía no hacer nada
// y además devolvía la lista a la página 1.
describe('Biblioteca: flujo de lectura', () => {
    it('el explorador del documento abre arriba de la pestaña y tiene ancla', () => {
        const explorer = bibliotecaTab.indexOf('id="fragmentos"');
        expect(explorer).toBeGreaterThan(-1);
        expect(explorer).toBeLessThan(bibliotecaTab.indexOf('Pendientes de aprobación'));
        expect(explorer).toBeLessThan(bibliotecaTab.indexOf('id="documentos"'));
    });

    it('abrir un documento salta a #fragmentos y conserva la página de la lista', () => {
        expect(source).toContain("return `/knowledge?document=${id}${offset > 0 ? `&documentOffset=${offset}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}#fragmentos`;");
        expect(source).not.toContain('href={`/knowledge?document=${document.id}`}');
        // El título también abre el documento (tabla y tarjeta).
        expect(bibliotecaTab.match(/href=\{documentReaderHref\(document\.id, documentOffset, searchQuery\)\}>\{document\.title\}<\/Link>/g)).toHaveLength(2);
    });

    it('volver a la lista regresa a la misma página y al listado', () => {
        expect(source).toContain('<Link href={libraryListHref(documentOffset, searchQuery)}>Volver a la lista</Link>');
        expect(source).toContain("return `/knowledge${params.size ? `?${params}` : ''}#documentos`;");
    });

    it('en móvil los fragmentos no van en una caja con scroll propio', () => {
        expect(source).not.toContain('grid max-h-[620px] gap-3 overflow-y-auto pr-2');
        expect(source).toContain('md:max-h-[620px] md:overflow-y-auto');
    });

    it('la lista va antes que las colecciones y los formularios de alta viven en «Subir»', () => {
        expect(bibliotecaTab.indexOf('id="documentos"')).toBeLessThan(bibliotecaTab.indexOf('>Colecciones</h2>'));
        expect(bibliotecaTab).not.toContain('action={createKnowledgeCollection}');
        expect(subirTab).toContain('action={createKnowledgeCollection}');
        expect(subirTab).toContain('Colecciones por defecto');
    });
});
