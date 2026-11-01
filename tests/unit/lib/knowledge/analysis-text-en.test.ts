import { describe, expect, it } from 'vitest';
import { analysisLabels, analysisToText, type LibraryAnalysis } from '@/lib/knowledge/analysis';
import { createTranslator } from '@/lib/i18n/translate';

const cite = (quote: string, page: number | null = 8) => ({
    chunk_id: 1, document_id: 1, title: 'Letter 1988', author: null, page_number: page, chunk_index: 0, quote,
    source_url: null, publication_date: null, document_type: 'letter',
});
const analysis: LibraryAnalysis = {
    tesis: [{ text: 'Buy with a discount', citation: cite('Quote one') }],
    error: { text: 'Overpaying', citation: cite('Quote two', null) },
    escenarios: [{ nombre: 'High', probabilidad: 50, disparador: 'Y rises' }],
    modelos: [{ nombre: 'Moat', text: 'Durable edge', citation: cite('Quote three') }],
    no_se: ['Current price'],
    probabilidades: 'Model estimate',
    aviso: 'Not financial advice.',
};

describe('texto copiable del análisis en inglés', () => {
    it('rótulos, autor y página en inglés', () => {
        const text = analysisToText(analysis, analysisLabels(createTranslator('en')));
        for (const h of ['Thesis', 'What would prove me wrong', 'Scenarios (Model estimate)', 'Mental models', "What I don't know"]) expect(text).toContain(h);
        expect(text).toContain('(Author not recorded · Letter 1988 · p. 8)');
        expect(text).toContain('(Author not recorded · Letter 1988 · page not recorded)');
        expect(text).toContain('- High: 50%. Trigger: Y rises');
    });
    it('en español, los rótulos del traductor dan el mismo texto que el de siempre', () => {
        expect(analysisToText(analysis, analysisLabels(createTranslator('es')))).toBe(analysisToText(analysis));
    });
});
