import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/corporate-actions.actions', () => ({
    applyCorporateAction: vi.fn(),
    getCorporateActions: vi.fn(async () => []),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import CorporateActionsView from '@/components/corporate-actions/CorporateActionsView';
import type { DataRecord } from '@/components/data/RecordViews';
import { LocaleProvider } from '@/lib/i18n/client';

// Dividendo de importe incierto tal como lo arma corporate_actions.py (frase leída
// del .py): dos importes distintos de Yahoo en la misma fecha ex, sin amount_per_share.
const PY = readFileSync('data-engine/app/api/routes/corporate_actions.py', 'utf8');
const template = /f"(Importe incierto: [^"]+)"/.exec(PY)?.[1] ?? '';
const values = ['0.5, 0.52', 'USD'];
const DESCRIPTION = template.replace(/\{[^}]+\}/g, () => values.shift() ?? '');

const uncertain: DataRecord = {
    id: null, ticker: 'ASTS', action_type: 'dividend', effective_date: '2026-10-30', ratio: null,
    description: DESCRIPTION, applied: null, applied_at: null, historical: false, no_position: false,
    declared: false, amount_per_share: null, currency: 'USD', pay_date: null, source: 'yahoo_finance',
};

describe('CorporateActionsView: dividendo de importe incierto', () => {
    it('la frase de prueba es la del backend', () => {
        expect(DESCRIPTION).toBe('Importe incierto: 0.5, 0.52 USD en la misma fecha ex');
    });
    it('en inglés se lee en inglés', () => {
        render(<LocaleProvider locale="en"><CorporateActionsView initialActions={[uncertain]} /></LocaleProvider>);
        expect(screen.getAllByText('Uncertain amount: 0.5, 0.52 USD on the same ex-date').length).toBeGreaterThan(0);
        expect(document.body.textContent).not.toContain('Importe incierto');
    });
    it('en castellano sigue la frase del backend', () => {
        render(<CorporateActionsView initialActions={[uncertain]} />);
        expect(screen.getAllByText(DESCRIPTION).length).toBeGreaterThan(0);
    });
});
