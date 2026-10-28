import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PaperProposalCard } from '@/components/proPicks/PaperProposalCard';
import type { PaperTradeView } from '@/lib/actions/paper-trading.actions';

const fixture = (over: Partial<PaperTradeView> = {}): PaperTradeView => ({
    id: 1, ticker: 'TEST', direction: 'long', horizon: 'short', thesis: 'Tesis sintética',
    conviction: '0.75', proposed_entry: '100.1234567', stop: '90', target: '120',
    inference_basis: 'Fixture local', status: 'open', currency: 'EUR',
    created_at: '2026-01-31T23:30:00Z', entry_price: '101', exit_price: null, mark_price: '110',
    mark_at: '2026-02-02T12:00:00Z', entry_at: '2026-02-01T12:00:00Z', exit_at: null,
    realized_pnl: '500', unrealized_pnl: '9', close_reason: null,
    realized_pnl_net: '490', unrealized_pnl_net: '8', quantity: '1', price_source: 'synthetic', ...over,
});
const value = (label: string) => screen.getByText(label).parentElement!;

describe('Paper proposal display without real orders', () => {
    it('separates proposed and observed prices and displays open results rather than realized amounts', () => {
        render(<PaperProposalCard trade={fixture({ cost_label: 'supuesto', entry_fee: '1' })} />);
        expect(screen.getByRole('article', { name: 'Propuesta simulada TEST' })).toBeVisible();
        expect(screen.getByRole('heading', { name: 'TEST · Largo · Operación a 30 días' })).toBeVisible();
        expect(screen.getByText('Abierta')).toBeVisible();
        expect(screen.getByText(/No es una orden al broker/)).toBeVisible();
        expect(value('Entrada propuesta')).toHaveTextContent('100,123457');
        expect(value('Entrada simulada')).toHaveTextContent('101');
        expect(value('Convicción del modelo')).toHaveTextContent('75 %');
        expect(screen.getByText(/no es una probabilidad de acierto validada/)).toBeVisible();
        expect(screen.getByText(/Creada:/)).toHaveTextContent('1/2/2026, 0:30:00');
        expect(screen.getByText('Resultado bruto simulado: 9 EUR')).toBeVisible();
        expect(screen.getByText(/Resultado neto simulado/)).toHaveTextContent('8 EUR');
        expect(screen.getByText(/Costes simulados/)).toHaveTextContent('salida estimada al cierre');
        expect(screen.queryByText(/Motivo de cierre/)).not.toBeInTheDocument();
        expect(screen.queryByText(/Dividendos devengados/)).not.toBeInTheDocument();
    });
    it('shows closed costs dividends and known corporate action warnings without rewriting amounts', () => {
        render(<PaperProposalCard trade={fixture({ direction: 'short', horizon: 'five_years', status: 'closed',
            close_reason: 'target', cost_label: 'supuesto', entry_fee: '1', exit_fee: '2',
            dividends_count: 2, dividends_total: '4', dividends_source: 'fixture', dividends_uncertain: 1,
            dividends_wrong_currency: 3, split_adjustments: 1, last_corporate_action: 'split 2:1',
            corporate_action_warning: 'split_cerrado_sin_ajustar',
        })} />);
        expect(screen.getByRole('heading', { name: 'TEST · Corto · Tesis 5 años' })).toBeVisible();
        expect(screen.getByText('Cerrada')).toBeVisible();
        expect(screen.getByText('Resultado bruto simulado: 500 EUR')).toBeVisible();
        expect(screen.getByText(/Resultado neto simulado/)).toHaveTextContent('490 EUR');
        expect(screen.getByText(/Costes simulados/)).toHaveTextContent('entrada 1 · salida 2');
        expect(screen.getByText(/Dividendos devengados/)).toHaveTextContent('2 eventos, fuente: fixture');
        expect(screen.getByText(/Dividendos devengados/)).toHaveTextContent('1 evento(s) incierto(s) excluido(s)');
        expect(screen.getByText(/Dividendos devengados/)).toHaveTextContent('3 en otra divisa ignorado(s), nunca convertidos');
        expect(screen.getByText('Ajustada por split: split 2:1.')).toBeVisible();
        expect(screen.getByRole('status')).toHaveTextContent('excluido de las estadísticas');
        expect(screen.getByText('Motivo de cierre: Objetivo')).toBeVisible();
    });
    it('uses honest fallbacks for unknown enums blank fields malformed numbers and invalid dates', () => {
        render(<PaperProposalCard trade={fixture({ direction: 'other', horizon: 'other', status: 'other',
            currency: null, thesis: '', inference_basis: '', conviction: '', proposed_entry: '', stop: 'NaN',
            target: 'Infinity', entry_price: null, mark_price: null, quantity: undefined, created_at: 'bad',
            entry_at: 'bad', mark_at: null, price_source: null, unrealized_pnl: null, unrealized_pnl_net: null,
            split_adjustments: 1, corporate_action_warning: 'custom-warning',
        } as unknown as Partial<PaperTradeView>)} />);
        expect(screen.getByRole('heading', { name: 'TEST · Sin dirección · Sin horizonte' })).toBeVisible();
        expect(screen.getByText('Estado no disponible')).toBeVisible();
        expect(screen.getByText('Tesis no disponible.')).toBeVisible();
        expect(screen.getByText('Razonamiento: Sin datos')).toBeVisible();
        expect(value('Convicción del modelo')).toHaveTextContent('Sin datos');
        expect(value('Objetivo propuesto')).toHaveTextContent('Sin datos');
        expect(screen.getByText('Ajustada por split: ajuste registrado.')).toBeVisible();
        expect(screen.getByRole('status')).toHaveTextContent('Acción corporativa registrada: custom-warning');
        expect(screen.getByRole('region', { name: 'Propuesta del modelo' })).toHaveTextContent('Sin divisa');
    });
    it.each(['-0.1', '1.1', 'NaN'])('rejects invalid conviction %s instead of claiming a probability', conviction => {
        render(<PaperProposalCard trade={fixture({ conviction })} />);
        expect(value('Convicción del modelo')).toHaveTextContent('Sin datos');
    });
    it.each(['0', '1'])('preserves conviction endpoint %s', conviction => {
        render(<PaperProposalCard trade={fixture({ conviction })} />);
        expect(value('Convicción del modelo')).toHaveTextContent(`${Number(conviction) * 100} %`);
    });
    it.each([['stop', 'Límite de pérdidas'], ['horizon', 'Fin del horizonte'], ['manual', 'Cierre anticipado'], ['legacy', 'Otro motivo registrado'], [null, 'Sin datos']])('labels closed reason %s', (close_reason, label) => {
        render(<PaperProposalCard trade={fixture({ status: 'closed', close_reason })} />);
        expect(screen.getByText(`Motivo de cierre: ${label}`)).toBeVisible();
    });
    it('keeps pending warnings and uncertain dividend counts separate from known events', () => {
        render(<PaperProposalCard trade={fixture({ status: 'pending', dividends_count: null, dividends_uncertain: 1,
            corporate_action_warning: 'split_pendiente_sin_ajustar', dividends_total: null,
        })} />);
        expect(screen.getByText('Pendiente de entrada')).toBeVisible();
        expect(screen.getByText(/Dividendos devengados/)).toHaveTextContent('Eventos no disponibles');
        expect(screen.getByRole('status')).toHaveTextContent('no se ejecuta');
        expect(within(screen.getByRole('region', { name: 'Precios observados' })).queryByText(/Motivo de cierre/)).not.toBeInTheDocument();
    });
});
