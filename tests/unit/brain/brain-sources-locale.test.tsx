import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrainSources } from '@/components/brain/BrainSources';
import { LocaleProvider } from '@/lib/i18n/client';
import type { PortfolioChatCitation } from '@/lib/chat/citations';

const citations: PortfolioChatCitation[] = [{
    chunk_id: 1,
    document: 'Carta 2021',
    page: null,
    locator: 'knowledge_chunk:1',
    source_type: 'knowledge_chunk',
    url: null,
}];

describe('BrainSources: etiquetas de tipo de fuente', () => {
    it('sigue al locale activo: Biblioteca en es, Library en en', () => {
        const { rerender } = render(
            <LocaleProvider locale="es"><BrainSources citations={citations} /></LocaleProvider>,
        );
        expect(screen.getByText('Biblioteca')).toBeInTheDocument();

        rerender(
            <LocaleProvider locale="en"><BrainSources citations={citations} /></LocaleProvider>,
        );
        expect(screen.getByText('Library')).toBeInTheDocument();
        expect(screen.queryByText('Biblioteca')).not.toBeInTheDocument();
    });
});
