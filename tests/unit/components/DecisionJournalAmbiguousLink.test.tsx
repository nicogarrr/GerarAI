import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/research.actions', () => ({
    createResearchDecision: vi.fn(),
    linkResearchDecisionTrade: vi.fn(),
    reviewResearchExpectations: vi.fn(),
}));
vi.mock('@/components/forms/MutationForm', () => ({
    MutationForm: ({ children, className }: { children: React.ReactNode; className?: string }) => (
        <form className={className}>{children}</form>
    ),
}));

import { DecisionAndRealityPanel } from '@/components/research/FundamentalModelPanels';

const trade = (id: number) => ({
    id,
    trade_date: '2026-03-10',
    action: 'buy',
    quantity: 5,
    price: 70,
    currency: 'USD',
});
const base = {
    id: 1,
    thesis_version_id: null,
    model_version_id: null,
    decision_date: '2026-03-10',
    decision: 'buy',
    rationale: 'Motivo de prueba',
    what_must_be_true: [],
    price: null,
    status: 'open',
    transaction_id: null,
    transaction: null,
};

function renderPanel(metadata: Record<string, unknown>) {
    return render(
        <DecisionAndRealityPanel
            ticker="UBER"
            decisions={[{ ...base, metadata }]}
            reviews={[]}
            trades={[trade(11), trade(12), trade(99)]}
        />,
    );
}

describe('Diario: resolución visible cuando hay varias operaciones posibles', () => {
    it('avisa, ofrece solo las candidatas y permite no enlazar', () => {
        renderPanel({ auto_link: { status: 'ambiguous', candidate_transaction_ids: [11, 12] } });
        expect(screen.getByTestId('journal-ambiguous-link')).toHaveTextContent('varias operaciones posibles');
        const select = screen.getByLabelText('Enlazar a una operación') as HTMLSelectElement;
        const values = within(select).getAllByRole('option').map((o) => (o as HTMLOptionElement).value);
        expect(values).toEqual(['', '11', '12']);
        expect(screen.getByRole('button', { name: /No enlazar/ })).toBeInTheDocument();
    });

    it('sin ambigüedad no muestra aviso, ofrece todas y no hay botón «No enlazar»', () => {
        renderPanel({});
        expect(screen.queryByTestId('journal-ambiguous-link')).not.toBeInTheDocument();
        const select = screen.getByLabelText('Enlazar a una operación') as HTMLSelectElement;
        expect(within(select).getAllByRole('option')).toHaveLength(4);
        expect(screen.queryByRole('button', { name: /No enlazar/ })).not.toBeInTheDocument();
    });
});

describe('Diario: enlace automático visible', () => {
    it('muestra el distintivo y permite corregir cuando está enlazada automáticamente', () => {
        render(
            <DecisionAndRealityPanel
                ticker="UBER"
                decisions={[{ ...base, transaction_id: 11, transaction: trade(11), metadata: { auto_link: { status: 'linked' } } } as never]}
                reviews={[]}
                trades={[trade(11)]}
            />,
        );
        expect(screen.getByTestId('journal-auto-link-badge')).toHaveTextContent('Enlace detectado automáticamente');
        expect(screen.getByRole('button', { name: 'Corregir / desenlazar' })).toBeTruthy();
    });
});

describe('Diario: sin candidatas vigentes no se ofrecen todas las operaciones', () => {
    it('no muestra selector si las candidatas ya no existen', () => {
        render(
            <DecisionAndRealityPanel
                ticker="UBER"
                decisions={[{ ...base, metadata: { auto_link: { status: 'ambiguous', candidate_transaction_ids: [1, 2] } } } as never]}
                reviews={[]}
                trades={[trade(11), trade(99)]}
            />,
        );
        expect(screen.queryByLabelText('Enlazar a una operación')).toBeNull();
        expect(screen.getByTestId('journal-unavailable-link')).toHaveTextContent('Las operaciones sugeridas ya no están disponibles');
        expect(screen.queryByTestId('journal-ambiguous-link')).toBeNull();
        expect(screen.getByRole('button', { name: 'No enlazar (sin operación)' })).toBeTruthy();
    });
});

describe('Diario: sugerencia sin confirmar', () => {
    it('ofrece solo la candidata y no la presenta como vínculo', () => {
        render(
            <DecisionAndRealityPanel
                ticker="UBER"
                decisions={[{ ...base, metadata: { auto_link: { status: 'suggested', candidate_transaction_id: 11 } } } as never]}
                reviews={[]}
                trades={[trade(11), trade(99)]}
            />,
        );
        expect(screen.getByTestId('journal-suggested-link')).toHaveTextContent('Sugerencia sin confirmar');
        expect(screen.getByRole('button', { name: 'Confirmar enlace' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'No enlazar (sin operación)' })).toBeTruthy();
    });
});

describe('Diario: sin operación explícita', () => {
    it('distingue la decisión de no enlazar', () => {
        renderPanel({ auto_link: { status: 'user_unlinked' } });
        expect(screen.getByTestId('journal-no-operation')).toHaveTextContent('Sin operación por elección del usuario');
        expect(screen.queryByTestId('journal-suggested-link')).toBeNull();
    });
});
