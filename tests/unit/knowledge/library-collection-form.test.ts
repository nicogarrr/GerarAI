import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const source = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');

// Auditoría UX 2026-10-29 (P0.5, medido en prod): lo primero tras las cifras
// era el formulario «Nueva colección» y el campo Tipo enseñaba el valor
// interno «custom». La lista de colecciones va primero y el tipo se elige
// con etiquetas en español.
describe('Biblioteca: formulario de nueva colección', () => {
    it('muestra la lista de colecciones antes que el formulario de alta', () => {
        const list = source.indexOf('<h2 className="mb-3 font-semibold text-gray-100">Colecciones</h2>');
        const form = source.indexOf('action={createKnowledgeCollectionResult}');
        expect(list).toBeGreaterThan(-1);
        expect(form).toBeGreaterThan(list);
    });

    it('el tipo de colección es un select con etiqueta humana, no el valor interno «custom»', () => {
        expect(source).not.toContain('defaultValue="custom" placeholder="Tipo de colección"');
        const field = source.slice(source.indexOf('name="collection_type"') - 400, source.indexOf('name="collection_type"') + 600);
        expect(field).toContain('<select');
        expect(field).toContain('>Personalizada</option>');
    });

    it('sigue enviando «custom» como valor por defecto al backend', () => {
        expect(source).toContain('<option value="custom">Personalizada</option>');
    });
});
