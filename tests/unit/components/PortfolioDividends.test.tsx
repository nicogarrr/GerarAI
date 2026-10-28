import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

vi.mock('@/components/portfolio/SyncDividendsButton', () => ({ default: ({ userId }: { userId: string }) => <button>sync-{userId}</button> }));
import PortfolioDividends from '@/components/portfolio/PortfolioDividends';

beforeAll(() => {
    // jsdom no implementa matchMedia (lo usa Panel).
    window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as any;
});

function proj(over: Record<string, unknown> = {}): any {
    return {
        as_of: '2026-10-01', base_currency: 'EUR', horizon_months: 12, label: 'x', method: 'm',
        fiscal_conditions: ['Condicion A'], sources: {}, months: [], fiscal_by_year: {}, positions: [],
        declared_future: [],
        coverage: { with_data: 0, sin_datos: [], fx_missing: [], unknown_source_withholding: [] },
        ...over,
    };
}
const position = (over: Record<string, unknown> = {}) => ({
    ticker: 'KO', currency: 'USD', quantity: 10.5, frequency_last_year: 4, gross_native: 100, gross_base: 90,
    domicile_country: 'US', source_withholding_rate: 0.15, source_withheld_base: 13.5, months: {}, ...over,
});

describe('PortfolioDividends vacio', () => {
    it('sin posiciones: Sin datos, no un cero', () => {
        render(<PortfolioDividends projection={proj()} />);
        expect(screen.getByText(/Sin datos: ninguna posición/)).toBeInTheDocument();
        expect(screen.queryByText(/0,00/)).not.toBeInTheDocument();
    });

    it('sin posiciones pero con importes inciertos lo dice y no promete proyeccion', () => {
        render(<PortfolioDividends projection={proj({ coverage: { with_data: 0, sin_datos: [], uncertain_dividends: ['AAA'], fx_missing: [], unknown_source_withholding: [] } })} />);
        expect(screen.getByText('Sin proyección: importe de dividendo incierto.')).toBeInTheDocument();
        expect(screen.getByText('Importe de dividendo incierto (excluidos del total):')).toBeInTheDocument();
    });

    it('boton de sincronizar solo con userId', () => {
        const { rerender } = render(<PortfolioDividends projection={proj()} userId="u9" />);
        expect(screen.getByText('sync-u9')).toBeInTheDocument();
        rerender(<PortfolioDividends projection={proj()} />);
        expect(screen.queryByText('sync-u9')).not.toBeInTheDocument();
    });
});

describe('PortfolioDividends bruto proyectado', () => {
    const gross = (over = {}) => ({ label: 'l', gross_total_base: 1234.5, gross_unverified_base: 0, net_irpf: 'N/D', ...over });

    it('bruto 0 no pinta la frase', () => {
        render(<PortfolioDividends projection={proj({ gross_summary: gross({ gross_total_base: 0 }), positions: [position()] })} />);
        expect(screen.queryByText(/Bruto proyectado/)).not.toBeInTheDocument();
    });

    it('completo vs parcial', () => {
        const { unmount } = render(<PortfolioDividends projection={proj({ gross_summary: gross({ complete: true }), positions: [position()] })} />);
        expect(screen.getByText(/Bruto proyectado a 12 meses/)).toBeInTheDocument();
        unmount();
        render(<PortfolioDividends projection={proj({ gross_summary: gross({ complete: false }), positions: [position()] })} />);
        expect(screen.getByText(/Bruto parcial proyectado/)).toBeInTheDocument();
    });

    it('declara siempre que es INFERIDO, y lo no incluido por falta de FX / sin dividendos', () => {
        render(<PortfolioDividends projection={proj({
            gross_summary: gross({ gross_unverified_base: 200 }), positions: [position()],
            coverage: { with_data: 1, sin_datos: ['ZZZ'], fx_missing: ['A', 'B'], unknown_source_withholding: [] },
        })} />);
        const p = screen.getByText(/Bruto proyectado/).closest('p')!;
        expect(p.textContent).toContain('INFERIDO');
        expect(p.textContent).toMatch(/de ellos .*200.* con retención en origen no ver/);
        expect(p.textContent).toMatch(/No incluye: 2 posiciones/);
        expect(p.textContent).toContain('Sin dividendos registrados: ZZZ');
    });
});

describe('PortfolioDividends escenarios y meses', () => {
    it('tarjeta de ano: null es N/D, tipo medio efectivo y excluidos', () => {
        render(<PortfolioDividends projection={proj({
            positions: [position()],
            fiscal_by_year: { '2026': { gross_base: 500, irpf_scenario: null, source_withheld_foreign: 75, retencion_a_cuenta_es: null,
                double_tax_deduction: null, cuota_pendiente_estimada: null, net_scenario: null, effective_avg_rate: 0.1934,
                covered_tickers: [], excluded_tickers: ['BN'], note: 'Base no EUR' } },
        })} />);
        const card = screen.getByText('Escenario 2026').closest('div')!;
        expect(within(card).getByText('IRPF (escenario)').nextSibling!.textContent).toBe('N/D');
        expect(card.textContent).toMatch(/19,3%/);
        expect(card.textContent).toMatch(/excluye BN \(sin datos, no cero\)/);
        expect(card.textContent).toContain('Base no EUR');
    });

    it('sin tipo medio efectivo no se pinta la fila', () => {
        render(<PortfolioDividends projection={proj({ positions: [position()],
            fiscal_by_year: { '2026': { gross_base: 1, irpf_scenario: 0, source_withheld_foreign: 0, retencion_a_cuenta_es: 0, double_tax_deduction: 0, cuota_pendiente_estimada: 0, net_scenario: 1, covered_tickers: [], excluded_tickers: [], note: '' } } })} />);
        expect(screen.queryByText('Tipo medio efectivo')).not.toBeInTheDocument();
    });

    it('mes a mes vacio dice que no hay pagos', () => {
        render(<PortfolioDividends projection={proj({ positions: [position()], months: [
            { month: '2026-11', gross_base: 0, source_withheld_base: 0, covered_tickers: [], excluded_tickers: [], note: null }] })} />);
        expect(screen.getByText(/Ningún pago proyectado en los próximos 12 meses/)).toBeInTheDocument();
    });

    it('mes con cobertura, mes solo no verificado y mes excluido', () => {
        render(<PortfolioDividends projection={proj({ positions: [position()], months: [
            { month: '2026-11', gross_base: 100, source_withheld_base: 15, gross_unverified_base: 40, covered_tickers: ['KO'], excluded_tickers: ['XX'], note: null },
            { month: '2026-12', gross_base: 0, source_withheld_base: 0, gross_unverified_base: 55, covered_tickers: [], excluded_tickers: ['ZZ'], note: null },
            { month: '2027-01', gross_base: 0, source_withheld_base: 0, covered_tickers: [], excluded_tickers: ['YY'], note: null },
            { month: '2027-02', gross_base: 0, source_withheld_base: 0, covered_tickers: [], excluded_tickers: [], note: null },
        ] })} />);
        const table = within(screen.getByRole('region', { name: 'Proyección mes a mes' }));
        const rows = table.getAllByRole('row').slice(1);
        expect(rows).toHaveLength(3); // el mes 2027-02 sin tickers se filtra
        expect(rows[0].textContent).toMatch(/nov.? 2026/);
        expect(rows[0].textContent).toMatch(/\+ .*40.* bruto, retención sin verific/);
        expect(rows[0].textContent).toContain('Excluidas sin datos: XX');
        expect(rows[1].textContent).toContain('bruto, retención sin verificar');
        expect(rows[1].querySelectorAll('td')[2].textContent).toBe('N/D');
        expect(rows[2].querySelectorAll('td')[1].textContent).toBe('N/D');
    });
});

describe('PortfolioDividends posiciones', () => {
    it('cantidad fraccionaria con coma y 6 decimales; retencion con pais', () => {
        render(<PortfolioDividends projection={proj({ positions: [position({ quantity: 0.000001, source_withholding_rate: 0.195 })] })} />);
        expect(screen.getAllByText('0,000001').length).toBeGreaterThan(0);
        expect(document.body.textContent).toMatch(/19,5%/);
        expect(document.body.textContent).toContain('(US)');
    });

    it('techo de convenio avisa que la retencion efectiva puede ser mayor', () => {
        render(<PortfolioDividends projection={proj({ positions: [position({ withholding_kind: 'techo_convenio', scenario_conditions: 'Con W-8BEN' })] })} />);
        expect(screen.getAllByText(/techo de convenio \(escenario\)/).length).toBeGreaterThan(0);
        expect(screen.getAllByText('Con W-8BEN').length).toBeGreaterThan(0);
    });

    it('retencion sin verificar: N/D y motivo; sin pais no pinta parentesis; importes null N/D', () => {
        render(<PortfolioDividends projection={proj({ positions: [position({
            source_withholding_rate: null, source_withheld_base: null, gross_base: null, domicile_country: null, unverified_reason: 'Sin domicilio fiscal',
            scenario_conditions: 'no debe verse' })] })} />);
        expect(screen.getAllByText('Sin domicilio fiscal').length).toBeGreaterThan(0);
        expect(screen.queryByText('no debe verse')).not.toBeInTheDocument();
        expect(screen.queryByText('(US)')).not.toBeInTheDocument();
        const card = screen.getByLabelText('Proyección por posición (tarjetas)');
        expect(within(card).getByText('Bruto (EUR)').nextSibling!.textContent).toBe('N/D');
        expect(within(card).getByText('Retenido (EUR)').nextSibling!.textContent).toBe('N/D');
    });

    it('tickers se enlazan a su ficha con encode', () => {
        render(<PortfolioDividends projection={proj({ positions: [position({ ticker: 'BRK/B' })] })} />);
        expect(screen.getAllByRole('link', { name: 'BRK/B' })[0]).toHaveAttribute('href', '/research/BRK%2FB');
    });
});

describe('PortfolioDividends declarados y cobertura', () => {
    const item = (over = {}) => ({ ticker: 'KO', ex_date: '2026-11-14', pay_date: null, amount_per_share: 0.51, currency: 'USD',
        label: 'DECLARADO', source: 'fmp', projection_as_of: '2026-10-01', note: 'No verificado', ...over });

    it('nota compartida va en la descripcion, una sola vez; pago sin fecha N/D', () => {
        render(<PortfolioDividends projection={proj({ declared_future: [item(), item({ ticker: 'PEP' })] })} />);
        expect(screen.getAllByText(/No verificado/)).toHaveLength(1);
        expect(screen.getByText(/Datos al/)).toBeInTheDocument();
        expect(document.body.textContent).toMatch(/pago N\/D/);
    });

    it('notas distintas van en cada linea', () => {
        render(<PortfolioDividends projection={proj({ declared_future: [item({ note: 'n1' }), item({ ticker: 'PEP', note: 'n2' })] })} />);
        expect(screen.getByText('n1')).toBeInTheDocument();
        expect(screen.getByText('n2')).toBeInTheDocument();
    });

    it('cobertura: motivos por ticker con texto de reserva', () => {
        render(<PortfolioDividends projection={proj({ positions: [position()], coverage: { with_data: 1, sin_datos: [], fx_missing: ['F'],
            unknown_source_withholding: ['U1', 'U2'], unverified_reasons: { U1: 'razon uno' } } })} />);
        expect(screen.getByText('Fuera de la proyección:')).toBeInTheDocument();
        expect(screen.getByText(/U1: razon uno/)).toBeInTheDocument();
        expect(screen.getByText(/U2: retención no verificada/)).toBeInTheDocument();
        expect(screen.getByText(/Sin tipo de cambio:/)).toBeInTheDocument();
    });

    it('supuestos fiscales se listan', () => {
        render(<PortfolioDividends projection={proj({ positions: [position()], fiscal_conditions: ['Condicion A', 'Condicion B'] })} />);
        expect(screen.getByText('Condicion B')).toBeInTheDocument();
    });
});
