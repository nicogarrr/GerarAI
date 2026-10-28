import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ChangeImpactCard } from '@/components/research/ChangeImpactCard';

// REPRO (rojo): plural mal escrito "afirmaciónes" (debe ser "afirmaciones").
it('plural correcto en español', () => {
    render(<ChangeImpactCard change={{ summary: 's', materiality_score: 1, requires_review: false, created_at: '2026-10-01T10:00:00Z', affected_metrics: [], affected_claim_ids: [1, 2] } as never} directionLabel="d" ticker="X" typeLabel="t" />);
    expect(screen.getByText(/Toca:/).textContent).toContain('2 afirmaciones de la tesis');
});
