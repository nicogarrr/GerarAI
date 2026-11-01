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
    red_team_score: 70,
    ...over,
} as unknown as ResearchThesis);

function riskBar(): HTMLElement {
    const label = screen.getByText('Riesgo de valoración');
    const card = label.closest('.min-w-0');
    expect(card).not.toBeNull();
    const bar = card!.querySelector('.h-1\\.5.rounded-full:not(.bg-gray-800)');
    expect(bar).not.toBeNull();
    return bar as HTMLElement;
}

describe('ThesisMemo barra de riesgo de valoración', () => {
    it('riesgo alto (75 = especulativa) se pinta en rojo, no en verde', () => {
        render(
            <ThesisMemo model={{ publishable: false }} thesis={thesis({ valuation_risk_score: 75 })} />,
        );
        expect(riskBar().className).toContain('bg-red-400');
        expect(riskBar().className).not.toContain('bg-teal-400');
    });
    it('riesgo bajo (20) se pinta en verde', () => {
        render(
            <ThesisMemo model={{ publishable: false }} thesis={thesis({ valuation_risk_score: 20 })} />,
        );
        expect(riskBar().className).toContain('bg-teal-400');
    });
    it('las barras de calidad siguen sin invertir (80 en verde)', () => {
        render(
            <ThesisMemo model={{ publishable: false }} thesis={thesis({ valuation_risk_score: 45 })} />,
        );
        const label = screen.getByText('Confianza en datos');
        const bar = label.closest('.min-w-0')!.querySelector('.h-1\\.5.rounded-full:not(.bg-gray-800)') as HTMLElement;
        expect(bar.className).toContain('bg-teal-400');
        expect(riskBar().className).toContain('bg-amber-400');
    });
});
