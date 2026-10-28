import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrainGuideAnswer } from '@/components/brain/BrainGuideAnswer';
import type { AssistantResponse } from '@/lib/research/assistant-contract';

const response = (overrides: Partial<AssistantResponse> = {}): AssistantResponse => ({
    mode: 'guide', status: 'answered', answer: 'Respuesta de prueba sin cifras.',
    sections: [{ key: 'facts', body: 'Hecho de prueba.', citation_ids: ['filing'] }],
    citations: [{ id: 'filing', kind: 'document_chunk', source: 'Informe de prueba', url: 'https://example.org/report', as_of: null, excerpt: null }],
    missing_data: [], suggested_next_steps: [], review_id: null, writeback: false,
    ...overrides,
});

describe('BrainGuideAnswer: fuentes comprobables y mensajes sin motivos inventados', () => {
    it('enlaza cada sección con la fuente concreta, no solo con un contador', () => {
        render(<BrainGuideAnswer result={response()} />);
        const references = screen.getByRole('list', { name: 'Fuentes de esta sección' });
        const reference = within(references).getByRole('link', { name: 'Fuente 1: Informe de prueba' });
        const target = document.getElementById(reference.getAttribute('href')!.slice(1));
        expect(target).toHaveTextContent('Informe de prueba');
        expect(within(target!).getByRole('link')).toHaveAttribute('href', 'https://example.org/report');
    });
    it('conserva el orden del catálogo y no duplica citas en la misma sección', () => {
        render(<BrainGuideAnswer result={response({ sections: [{ key: 'facts', body: 'Texto', citation_ids: ['filing', 'filing'] }] })} />);
        expect(within(screen.getByRole('list', { name: 'Fuentes de esta sección' })).getAllByRole('link')).toHaveLength(1);
    });
    it('avisa si la referencia apunta a una fuente ausente sin fabricar un enlace', () => {
        render(<BrainGuideAnswer result={response({ citations: [] })} />);
        expect(screen.getByText(/Referencia sin fuente disponible/)).toBeInTheDocument();
        expect(screen.queryByRole('link')).not.toBeInTheDocument();
        expect(screen.getByText(/El asistente no ha adjuntado fuentes/)).toBeInTheDocument();
    });
    it('no presenta como citada una sección que no tiene referencias', () => {
        render(<BrainGuideAnswer result={response({ sections: [{ key: 'hypotheses', body: 'Hipótesis de prueba.', citation_ids: [] }] })} />);
        expect(screen.getByText(/Sin citas para esta sección: comprueba/)).toBeInTheDocument();
    });
    it('no deduce por qué una sección llegó vacía ni promete una lista inexistente', () => {
        render(<BrainGuideAnswer result={response({ status: 'insufficient_data', answer: '  ', sections: [{ key: 'facts', body: '', citation_ids: [] }] })} />);
        expect(screen.getByText(/no indica el motivo de este apartado vacío/)).toBeInTheDocument();
        expect(screen.getByText(/no ha indicado qué información falta/)).toBeInTheDocument();
        expect(screen.queryByText(/porque la evidencia no daba/)).not.toBeInTheDocument();
        expect(screen.queryByText(/Lo que falta está enumerado/)).not.toBeInTheDocument();
    });
    it('una respuesta vacía no afirma que existan secciones o citas cuando no existen', () => {
        render(<BrainGuideAnswer result={response({ answer: '', sections: [], citations: [] })} />);
        expect(screen.getByText(/El asistente ha devuelto la respuesta sin texto/)).toBeInTheDocument();
        expect(screen.queryByText(/Lo que sí ha enviado/)).not.toBeInTheDocument();
    });
    it('mantiene las URLs inseguras como texto sin convertirlas en enlaces externos', () => {
        const fixture = response();
        fixture.citations[0].url = 'javascript:alert(1)';
        render(<BrainGuideAnswer result={fixture} />);
        expect(screen.queryByRole('link', { name: /^Informe de prueba/ })).not.toBeInTheDocument();
    });
    it('dos respuestas no comparten el destino de sus referencias', () => {
        const { container } = render(<><BrainGuideAnswer result={response()} /><BrainGuideAnswer result={response()} /></>);
        const links = screen.getAllByRole('link', { name: 'Fuente 1: Informe de prueba' });
        expect(links[0].getAttribute('href')).not.toBe(links[1].getAttribute('href'));
        const ids = [...container.querySelectorAll('[id]')].map((item) => item.id);
        expect(new Set(ids).size).toBe(ids.length);
    });
});
