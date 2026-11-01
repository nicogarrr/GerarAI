// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    citationKindLabel, citationKindLabelFor, toChatCitations, toPortfolioChatCitations,
    type ChatSource,
} from '@/lib/chat/citations';

describe('toChatCitations', () => {
    it('sin sources devuelve []', () => {
        expect(toChatCitations(undefined)).toEqual([]);
        expect(toChatCitations(null)).toEqual([]);
    });
    it('solo convierte tipos cita (chunks); el resto se omite', () => {
        const sources: ChatSource[] = [
            { type: 'document_chunk', id: 7, title: 'Carta Buffett 2008', page_number: 3, source_type: 'carta' },
            { type: 'portfolio', id: 1, title: 'Cartera' },
            { type: 'position', id: 2, title: 'Posición SAN' },
        ];
        expect(toChatCitations(sources)).toEqual([
            { chunk_id: 7, document: 'Carta Buffett 2008', page: 3, locator: 'document_chunk:7', source_type: 'carta' },
        ]);
    });
    it('claim_evidence usa document_chunk_id como chunk y locator propio', () => {
        const [c] = toChatCitations([{ type: 'claim_evidence', id: 99, document_chunk_id: 42, title: 'Evidencia' }]);
        expect(c.chunk_id).toBe(42);
        expect(c.locator).toBe('claim_evidence:99');
    });
    it('sin título deriva «Documento <id>»; sin nada, «Documento»', () => {
        const [a, b] = toChatCitations([
            { type: 'rag_chunk', id: 1, title: '', document_id: 55 },
            { type: 'knowledge_chunk', id: 2, title: '' },
        ]);
        expect(a.document).toBe('Documento 55');
        expect(b.document).toBe('Documento');
    });
    it('página solo si es número; source_type solo si es string', () => {
        const [c] = toChatCitations([{ type: 'document_chunk', id: 1, title: 'X', page_number: '3' as never, source_type: 5 as never }]);
        expect(c.page).toBeNull();
        expect(c.source_type).toBeNull();
    });
});

describe('toPortfolioChatCitations', () => {
    it('deduplica por tipo:id', () => {
        const out = toPortfolioChatCitations([
            { type: 'position', id: 2, title: 'Posición SAN' },
            { type: 'position', id: 2, title: 'Posición SAN' },
        ]);
        expect(out).toHaveLength(1);
    });
    it('el mismo documento citado por varios fragmentos aparece una vez (por documento y página)', () => {
        const out = toPortfolioChatCitations([
            { type: 'document_chunk', id: 10, title: 'Carta', document_id: 5, page_number: 3 },
            { type: 'document_chunk', id: 11, title: 'Carta', document_id: 5, page_number: 3 },
            { type: 'document_chunk', id: 12, title: 'Carta', document_id: 5, page_number: 4 },
        ]);
        expect(out).toHaveLength(2);
    });
    it('dos documentos distintos con el mismo título NO se fusionan (identidad por id)', () => {
        const out = toPortfolioChatCitations([
            { type: 'document_chunk', id: 10, title: 'Informe anual', document_id: 5, page_number: 3 },
            { type: 'document_chunk', id: 11, title: 'Informe anual', document_id: 6, page_number: 3 },
        ]);
        expect(out).toHaveLength(2);
    });
    it.each([
        ['enlace interno de cartera', '/portfolio', '/portfolio'],
        ['ficha de research', '/research/MSFT', '/research/MSFT'],
        ['ficha con vista permitida', '/research/MSFT?view=thesis', '/research/MSFT?view=thesis'],
        ['vista de valoración (equipo de expertos)', '/research/BRK.B?view=valoracion', '/research/BRK.B?view=valoracion'],
        ['https externa', 'https://sec.gov/x', 'https://sec.gov/x'],
    ])('admite %s', (_e, input, expected) => {
        expect(toPortfolioChatCitations([{ type: 'position', id: 1, title: 'X', url: input }])[0].url).toBe(expected);
    });
    it.each([
        ['vista no permitida', '/research/MSFT?view=admin'],
        ['http con credenciales', 'https://user:pass@example.com/x'],
        ['esquema javascript', 'javascript:alert(1)'],
        ['URL rota', 'ht!tp://%%%'],
    ])('NO enlaza %s (procedencia sin link, nunca inventado)', (_e, input) => {
        expect(toPortfolioChatCitations([{ type: 'position', id: 1, title: 'X', url: input }])[0].url).toBeNull();
    });
    it('una fuente no-chunk conserva su título como documento y su tipo como source_type', () => {
        const [c] = toPortfolioChatCitations([{ type: 'position', id: 2, title: 'Posición SAN' }]);
        expect(c).toMatchObject({ chunk_id: 2, document: 'Posición SAN', page: null, locator: 'position:2', source_type: 'position', url: null });
    });
});

describe('citationKindLabel / citationKindLabelFor', () => {
    it('traduce tipos conocidos y devuelve null en desconocidos', () => {
        expect(citationKindLabel('thesis_version:3')).toBe('Tesis');
        expect(citationKindLabel('knowledge_chunk:1')).toBe('Biblioteca');
        expect(citationKindLabel('cosa_rara:1')).toBeNull();
    });
    it('no repite la etiqueta si el documento ya empieza por ella', () => {
        expect(citationKindLabelFor({ locator: 'position:2', document: 'Posición GOOGL' })).toBeNull();
        expect(citationKindLabelFor({ locator: 'position:2', document: 'SAN' })).toBe('Posición');
    });
});
