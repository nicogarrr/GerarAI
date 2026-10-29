import axe from 'axe-core';
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import { ResearchClaimForm } from '@/components/research/ResearchClaimForm';

// Barrido axe de la vista «tesis» de la ficha (29-oct-2026): el número de
// materialidad del alta de afirmaciones no tenía etiqueta (label, crítica).
describe('formulario de afirmaciones de la tesis', () => {
    it('todos los campos tienen nombre accesible (axe label = 0)', async () => {
        const { container, getByRole } = render(<ResearchClaimForm action={vi.fn(async () => ({ success: true }))} />);
        const result = await axe.run(container, { runOnly: { type: 'rule', values: ['label'] } });
        expect(result.violations.map((v) => v.nodes.map((n) => n.html).join(' | '))).toEqual([]);
        expect(getByRole('spinbutton', { name: 'Materialidad (0 a 10)' })).toHaveAttribute('name', 'materiality_score');
        expect(getByRole('textbox', { name: 'Afirmación' })).toHaveAttribute('name', 'statement');
    });
});
