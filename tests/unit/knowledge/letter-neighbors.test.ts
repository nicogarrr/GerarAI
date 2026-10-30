import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { groupLetters, letterNeighbors, type LetterDoc } from '@/app/(root)/inversores/cartas/letters';

const doc = (id: number, title: string, author: string | null, publication_date: string | null = null): LetterDoc => ({
    id, title, author, publication_date, document_type: 'fund_letter', source_url: null, status: 'ready',
});

// Lector de cartas (UX 30-oct): al terminar una carta no había forma de pasar
// a la siguiente del mismo autor sin volver a la lista y buscarla.
describe('cartas: anterior y siguiente del mismo autor', () => {
    const groups = groupLetters([
        doc(1, 'Berkshire 1985', 'Buffett'), doc(2, 'Berkshire 1986', 'Buffett'), doc(3, 'Berkshire 1987', 'Buffett'),
        doc(9, 'Oaktree memo 2001', 'Marks'),
    ]);

    it('la del medio tiene una más antigua y una más reciente', () => {
        const n = letterNeighbors(groups, 2);
        expect(n.older?.id).toBe(1);
        expect(n.newer?.id).toBe(3);
    });

    it('en los extremos falta un lado y nunca cruza de autor', () => {
        expect(letterNeighbors(groups, 3)).toEqual({ older: expect.objectContaining({ id: 2 }), newer: null });
        expect(letterNeighbors(groups, 1).older).toBeNull();
        expect(letterNeighbors(groups, 9)).toEqual({ older: null, newer: null });
        expect(letterNeighbors(groups, 404)).toEqual({ older: null, newer: null });
    });

    it('el lector enlaza ambas y la lista enlaza el título de cada carta', () => {
        const reader = readFileSync('app/(root)/inversores/cartas/[id]/page.tsx', 'utf8');
        expect(reader).toContain('letterNeighbors(groupLetters(await getKnowledgeLetters()), letterId)');
        expect(reader).toContain('← Carta anterior');
        expect(reader).toContain('Carta siguiente →');
        const list = readFileSync('app/(root)/inversores/cartas/page.tsx', 'utf8');
        expect(list).toContain('href={`/inversores/cartas/${letter.id}`}>{letter.title}</Link>');
    });
});
