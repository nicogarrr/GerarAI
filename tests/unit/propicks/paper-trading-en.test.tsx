import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/paper-trading.actions', () => ({ feedPaperProposalsNow: vi.fn(), getPaperTrading: vi.fn() }));

import { PaperCalibrationView } from '@/components/proPicks/PaperCalibrationView';
import { PaperProposalCard } from '@/components/proPicks/PaperProposalCard';
import { PaperTradingContent } from '@/components/proPicks/PaperTradingView';

const trade = {
    id: 7, ticker: 'MSFT', status: 'closed', direction: 'long', horizon: 'short', currency: 'USD', thesis: 'Cloud growth', conviction: '0.65',
    proposed_entry: '400', stop: '380', target: '440', inference_basis: 'Earnings beat', created_at: '2026-10-01T10:00:00Z',
    entry_price: '401.5', entry_at: '2026-10-02T14:00:00Z', mark_price: null, mark_at: null, exit_price: '440', exit_at: '2026-10-20T14:00:00Z',
    price_source: 'yahoo_finance_spot', quantity: '10', realized_pnl: '1234.5', realized_pnl_net: '1220', unrealized_pnl: null, unrealized_pnl_net: null,
    cost_label: 'supuesto', entry_fee: '1', exit_fee: '1', dividends_total: '3', dividends_count: 1, dividends_uncertain: 0, dividends_wrong_currency: 0, dividends_source: 'Yahoo',
    close_reason: 'target', thesis_version_id: 3, thesis_anchor: { id: 3, version: 2, created_at: '2026-09-30T10:00:00Z', latest_version: 3, superseded: true },
} as never;

describe('paper trading de Pro Picks en inglés', () => {
    beforeAll(() => {
        Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) });
    });

    it('la tarjeta de propuesta sale en inglés', () => {
        render(<PaperProposalCard locale="en" trade={trade} />);
        expect(screen.getByRole('heading', { name: 'MSFT · Long · 30-day trade' })).toBeInTheDocument();
        expect(screen.getByText('Closed')).toBeInTheDocument();
        expect(screen.getByText('65%')).toBeInTheDocument();
        expect(screen.getByText('Simulated gross result: 1,234.5 USD')).toBeInTheDocument();
        expect(screen.getByText('Close reason: Target')).toBeInTheDocument();
        expect(screen.getByText(/The thesis has changed since then \(current: v3\)/)).toBeInTheDocument();
        expect(screen.getByText(/Accrued dividends: 3 USD \(1 event, source: Yahoo\)/)).toBeInTheDocument();
        expect(document.body.textContent).not.toMatch(/Sin datos|Propuesta|Resultado|Motivo/);
    });

    it('en español la tarjeta no cambia', () => {
        render(<PaperProposalCard trade={trade} />);
        expect(screen.getByRole('heading', { name: 'MSFT · Largo · Operación a 30 días' })).toBeInTheDocument();
        expect(screen.getByText('65 %')).toBeInTheDocument();
        expect(screen.getByText('Motivo de cierre: Objetivo')).toBeInTheDocument();
        expect(screen.getByText(/Dividendos devengados: 3 USD \(1 evento, fuente: Yahoo\)/)).toBeInTheDocument();
    });

    it('el resumen y la calibración salen en inglés', () => {
        const data = { trades: [], score: { groups: [{ horizon: 'short', currency: 'USD', wins: 2, closed: 3, losses: 1, flat: 0, hit_rate: 0.6667, realized_pnl: '10', unrealized_pnl: '0', missing_marks: 0, realized_pnl_net: '9', closed_net: 3, closed_distorted: 0 }] } } as never;
        render(<PaperTradingContent data={data} locale="en" />);
        expect(screen.getByRole('heading', { name: 'AI paper results' })).toBeInTheDocument();
        expect(screen.getByText('66.67%')).toBeInTheDocument();
        expect(screen.getByText('3 of 3')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Generate paper proposals' })).toBeInTheDocument();
        expect(screen.getByText('Calibration not available. Conviction cannot be evaluated with this data.')).toBeInTheDocument();
    });

    it('calibración con grupos en inglés', () => {
        const calibration = { propuestas_llm: 12, cerradas_con_resultado: 4, muestra_insuficiente: true, minimo_cerradas: 20, aviso: null, brier: 0.21, brier_referencia_sin_informacion: 0.25, base: 'v1', bins: [{ rango: '0.6-0.8', cerradas: 4, conviction_media: 0.7, tasa_acierto: 0.5, hueco: -0.2, aviso: null }] } as never;
        render(<PaperCalibrationView data={calibration} locale="en" />);
        expect(screen.getByText('4 LLM proposals closed with a result, out of 12 recorded.')).toBeInTheDocument();
        expect(screen.getByText('Range 60% - 80% · 4 closed')).toBeInTheDocument();
        expect(screen.getAllByText('-20 pp').length).toBeGreaterThan(0);
        expect(screen.getByRole('columnheader', { name: 'Difference (pp)' })).toBeInTheDocument();
    });
});
