import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ThesisMemo from '@/components/research/ThesisMemo';
import type { ResearchThesis } from '@/lib/actions/research.actions';

const thesis = (over: Record<string, unknown>): ResearchThesis => ({
    id: 1,
    version: 36,
    rating: 'insufficient_data',
    status: 'insufficient_data',
    created_at: '2026-10-20T10:00:00Z',
    stale: false,
    thesis_markdown: 'Contenido de la tesis.',
    data_confidence_score: 80,
    source_coverage_score: 90,
    red_team_score: 13,
    ...over,
} as unknown as ResearchThesis);

describe('ThesisMemo leyenda de dirección de escala', () => {
    it('las barras de calidad indican «Mayor = mejor»', () => {
        render(<ThesisMemo model={{ publishable: false }} thesis={thesis({ valuation_risk_score: 45 })} />);
        expect(screen.getAllByText('Mayor = mejor').length).toBe(3);
    });
    it('la barra de riesgo de valoración indica «Mayor = más riesgo»', () => {
        render(<ThesisMemo model={{ publishable: false }} thesis={thesis({ valuation_risk_score: 45 })} />);
        expect(screen.getByText('Mayor = más riesgo')).toBeTruthy();
    });
});
