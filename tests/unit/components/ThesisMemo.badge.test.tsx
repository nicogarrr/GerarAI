import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ThesisMemo from '@/components/research/ThesisMemo';
import { canShowThesisText } from '@/components/research/ThesisSummary';
import type { ResearchThesis } from '@/lib/actions/research.actions';

const thesis = (over: Record<string, unknown>): ResearchThesis => ({
    id: 1,
    version: 36,
    rating: 'insufficient_data',
    status: 'insufficient_data',
    created_at: '2026-10-20T10:00:00Z',
    stale: false,
    thesis_markdown: 'Contenido de la tesis.',
    ...over,
} as unknown as ResearchThesis);

describe('ThesisMemo badges de cabecera', () => {
    it('estado y rating «datos insuficientes» se pintan una sola vez y en español', () => {
        render(<ThesisMemo model={{ publishable: false }} thesis={thesis({})} />);
        const matches = screen.getAllByText('datos insuficientes');
        expect(matches).toHaveLength(1);
        expect(screen.queryByText('insufficient data')).not.toBeInTheDocument();
    });
    it('estado y rating distintos muestran ambos badges', () => {
        // Con el modelo no publicable el rating se fija a «datos insuficientes»:
        // el estado publicada es distinto y debe seguir saliendo.
        render(<ThesisMemo model={{ publishable: false }} thesis={thesis({ status: 'published' })} />);
        expect(screen.getByText('datos insuficientes')).toBeInTheDocument();
        expect(screen.getByText('publicada')).toBeInTheDocument();
    });
    it('final is generated but not approved, without claiming it was unaudited', () => {
        render(<ThesisMemo model={{ publishable: true }} thesis={thesis({ status: 'final', rating: 'expensive' })} />);
        expect(screen.getByText('generada · pendiente de aprobación')).toBeInTheDocument();
        expect(screen.getByText(/Generación completada, pendiente de aprobación/)).toBeInTheDocument();
        expect(screen.queryByText('Borrador en revisión: texto sin auditar')).not.toBeInTheDocument();
        expect(canShowThesisText(thesis({ status: 'final' }), { publishable: true })).toBe(false);
    });
    it('a draft still carries the review warning', () => {
        render(<ThesisMemo model={{ publishable: true }} thesis={thesis({ status: 'draft' })} />);
        expect(screen.getByText('Borrador en revisión: texto sin auditar')).toBeInTheDocument();
    });
});
