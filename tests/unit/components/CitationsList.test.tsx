import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CitationsList from '@/components/chat/CitationsList';

const cita = {
    chunk_id: 7, document: 'Carta Buffett 2008', page: 3,
    locator: 'document_chunk:7', source_type: 'carta',
};

describe('CitationsList', () => {
    it('sin citas no renderiza nada', () => {
        const { container } = render(<CitationsList citations={[]} />);
        expect(container).toBeEmptyDOMElement();
    });
    it('muestra el número de citas, el documento, la página y la etiqueta del tipo', () => {
        render(<CitationsList citations={[cita]} />);
        expect(screen.getByText('Citas y evidencia (1)')).toBeInTheDocument();
        expect(screen.getByText('Carta Buffett 2008')).toBeInTheDocument();
        expect(screen.getByText('p. 3')).toBeInTheDocument();
        expect(screen.getByText('Documento')).toBeInTheDocument();
    });
    it('sin página no pinta el badge de página', () => {
        render(<CitationsList citations={[{ ...cita, page: null }]} />);
        expect(screen.queryByText(/^p\./)).not.toBeInTheDocument();
    });
    it('con sources crudos los deriva con la misma regla del módulo de citas', () => {
        render(<CitationsList citations={[]} sources={[{ type: 'knowledge_chunk', id: 2, title: 'Memo Howard Marks' }]} />);
        expect(screen.getByText('Memo Howard Marks')).toBeInTheDocument();
        expect(screen.getByText('Biblioteca')).toBeInTheDocument();
    });
    it('las citas explícitas tienen prioridad sobre los sources crudos', () => {
        render(<CitationsList citations={[cita]} sources={[{ type: 'knowledge_chunk', id: 2, title: 'Otro' }]} />);
        expect(screen.getByText('Carta Buffett 2008')).toBeInTheDocument();
        expect(screen.queryByText('Otro')).not.toBeInTheDocument();
    });
});
