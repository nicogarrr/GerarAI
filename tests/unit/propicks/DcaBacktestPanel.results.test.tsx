import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DcaBacktest, DcaBacktestPlan } from '@/lib/dca/types';

const { getDcaBacktest } = vi.hoisted(() => ({ getDcaBacktest: vi.fn() }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaBacktest }));
vi.mock('@/components/watchlist/DcaHitRatesCard', () => ({ default: () => <div data-testid="hit-rates" /> }));

import DcaBacktestPanel, { valuationLabel } from '@/components/proPicks/DcaBacktestPanel';

const plan = (key: string, over: Partial<DcaBacktestPlan> = {}): DcaBacktestPlan => ({
    key, label: key, invested: 1200, deployed: 1200, cash_left: 0, shares: 10, avg_cost: 120, final_value: 1500,
    multiple: 1.25, irr: 0.12, max_drawdown: -0.3, worst_unrealized: -0.2, buys: 12, ...over,
});

const result = (over: Partial<DcaBacktest> = {}): DcaBacktest => ({
    symbol: 'UBER', available: true, reason: null, params_version: 'v1', currency: 'USD', currency_label: 'US$',
    data_source: 'fmp', first_signal: '2016-01', last_signal: '2026-09', first_buy: null, last_buy: null,
    valued_at_period: '2026-09', valued_at_date: '2026-09-30', valued_month_complete: true, final_price: 80, months: 128,
    base_amount: 100, plans: [plan('plain'), plan('levels', { irr_vs_plain: 0.01, shares_per_money_vs_plain: 0.05 }), plan('fixed_budget', { value_vs_plain: -0.02 })],
    levels: [{ level: 1, label: 'Nivel 1', color: '#ff0000', months: 6 }], hit_rates: null, disclaimer: 'Histórico e hipotético.', ...over,
});

const form = () => screen.getByRole('button', { name: /ejecutar|calculando/i }).closest('form')!;
async function run(data: DcaBacktest | null, error: string | null = null) {
    getDcaBacktest.mockResolvedValue({ data, error });
    render(<DcaBacktestPanel />);
    fireEvent.submit(form());
    await waitFor(() => expect(getDcaBacktest).toHaveBeenCalledTimes(1));
}

beforeEach(() => getDcaBacktest.mockReset());

describe('DcaBacktestPanel: formulario', () => {
    it('el ticker se escribe en mayusculas, y sin ticker el boton queda deshabilitado', () => {
        render(<DcaBacktestPanel defaultSymbol="uber" />);
        const input = screen.getByLabelText('Ticker') as HTMLInputElement;
        fireEvent.change(input, { target: { value: 'msft' } });
        expect(input.value).toBe('MSFT');
        expect(screen.getByRole('button', { name: /ejecutar/i })).toBeEnabled();
        fireEvent.change(input, { target: { value: '   ' } });
        expect(screen.getByRole('button', { name: /ejecutar/i })).toBeDisabled();
    });

    it('envia ticker, fechas vacias como undefined y la base numerica; mientras corre el boton esta deshabilitado', async () => {
        let resolve!: (v: { data: DcaBacktest | null; error: string | null }) => void;
        getDcaBacktest.mockReturnValue(new Promise((r) => { resolve = r; }));
        render(<DcaBacktestPanel defaultSymbol="msft" />);
        fireEvent.change(screen.getByLabelText(/desde \(mes\)/i), { target: { value: '' } });
        fireEvent.submit(form());
        await waitFor(() => expect(getDcaBacktest).toHaveBeenCalledTimes(1));
        expect(getDcaBacktest.mock.calls[0][0]).toEqual({ symbol: 'msft', start: undefined, end: undefined, base: 100 });
        await waitFor(() => expect(screen.getByRole('button', { name: /calculando/i })).toBeDisabled());
        resolve({ data: null, error: null });
        await waitFor(() => expect(screen.getByRole('button', { name: /ejecutar$/i })).toBeEnabled());
    });
});

describe('DcaBacktestPanel: frontera de la aportacion', () => {
    it('aportacion 0: alerta de base positiva y no llama al backend', async () => {
        render(<DcaBacktestPanel />);
        fireEvent.change(screen.getByLabelText(/aportación base/i), { target: { value: '0' } });
        fireEvent.submit(form());
        expect(await screen.findByRole('alert')).toHaveTextContent('Introduce una aportación base mayor que 0.');
        expect(getDcaBacktest).not.toHaveBeenCalled();
    });
});

describe('DcaBacktestPanel: resultado', () => {
    it('un error del servicio se muestra como alerta y no pinta tabla', async () => {
        await run(null, 'backend caido');
        expect(await screen.findByRole('alert')).toHaveTextContent('backend caido');
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('sin datos suficientes: usa el motivo si lo hay y el texto generico si no', async () => {
        await run(result({ available: false, reason: null, plans: [] }));
        const generic = await screen.findByText('Sin datos suficientes para ese rango.');
        expect(generic.textContent?.length).toBeGreaterThan(0);
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('con datos: tabla con importes en moneda, TIR en porcentaje, notas de niveles y presupuesto fijo, niveles y descargo', async () => {
        await run(result());
        const table = await screen.findByRole('table');
        const rows = within(table).getAllByRole('row');
        expect(rows).toHaveLength(8); // cabecera + 7 metricas
        expect(within(table).getAllByRole('columnheader')).toHaveLength(4); // metrica + 3 planes
        expect(table.textContent).toMatch(/12,0\s?%/); // irr 0.12
        expect(table.textContent).toMatch(/1\.200,00/); // invertido
        expect(screen.queryByText('Sin datos suficientes para ese rango.')).not.toBeInTheDocument();
        expect(screen.getByTestId('hit-rates')).toBeInTheDocument();
        expect(screen.getByText('Histórico e hipotético.')).toBeInTheDocument();
        expect(screen.getAllByRole('listitem')).toHaveLength(2); // notas niveles + presupuesto fijo
        expect(document.querySelector('span[style*="background-color"]')).not.toBeNull(); // chip de nivel
        expect(screen.getByText(/2016-01/)).toBeInTheDocument();
    });

    it('solo plan plano y sin niveles: no hay notas comparativas ni chips; los nulos salen como raya y cash 0 como raya', async () => {
        await run(result({
            plans: [plan('plain', { irr: null, avg_cost: null, cash_left: 0 })],
            levels: [],
            first_signal: null,
            last_signal: null,
            params_version: null,
            currency: null,
            currency_label: null,
        }));
        const table = await screen.findByRole('table');
        expect(screen.queryAllByRole('listitem')).toHaveLength(0);
        expect(document.querySelector('span[style*="background-color"]')).toBeNull();
        expect(document.querySelector('.flex-wrap.gap-2')).toBeNull();
        const rowText = (name: RegExp) => within(table).getAllByRole('row').find((r) => name.test(r.textContent ?? ''))!.textContent;
        expect(rowText(/TIR anual/i)).toContain('—');
        expect(rowText(/coste medio/i)).toContain('—');
        expect(rowText(/caja sin invertir/i)).toContain('—');
        // sin moneda no se anade «precios en …»
        expect(screen.getByText(/—/, { selector: 'p.text-xs' })).toBeInTheDocument();
    });

    it('cash restante positivo se muestra como importe, no como raya', async () => {
        await run(result({ plans: [plan('plain', { cash_left: 345.5 })] }));
        const table = await screen.findByRole('table');
        const row = within(table).getAllByRole('row').find((r) => /caja sin invertir/i.test(r.textContent ?? ''))!;
        expect(row.textContent).toMatch(/345,50/);
    });
});

describe('valuationLabel', () => {
    it('mes cerrado: valorado al cierre del periodo, N/D si falta', () => {
        expect(valuationLabel({ valued_at_period: '2026-09', valued_at_date: '2026-09-30', valued_month_complete: true })).toBe('valorado al cierre de 2026-09');
        expect(valuationLabel({ valued_at_period: null, valued_month_complete: true })).toBe('valorado al cierre de N/D');
        expect(valuationLabel({ valued_at_period: null }, 'en')).toBe('valued at the close of n/a');
        expect(valuationLabel({ valued_at_period: '2026-09', valued_month_complete: true }, 'en')).toBe('valued at the close of 2026-09');
    });
    it('mes en curso con fecha: ultimo cierre disponible, en ambos idiomas; sin fecha cae al cierre del periodo', () => {
        const base = { valued_at_period: '2026-10', valued_at_date: '2026-10-21', valued_month_complete: false };
        expect(valuationLabel(base)).toMatch(/^valorado al último cierre disponible \(.+, mes en curso\)$/);
        expect(valuationLabel(base, 'en')).toMatch(/^valued at the latest available close \(.+, month in progress\)$/);
        expect(valuationLabel({ ...base, valued_at_date: null })).toBe('valorado al cierre de 2026-10');
    });
});
