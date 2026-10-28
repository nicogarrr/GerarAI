import { beforeAll, describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import PortfolioForecast from '@/components/portfolio/PortfolioForecast';

beforeAll(() => {
    window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as any;
});

const portfolio = (over: Record<string, unknown> = {}) => ({
    total_value_base: 10000, position_count: 2, covered_count: 2, excluded_count: 0, covered_weight: 1,
    scenarios: {
        bear: { contribution_cagr: -0.05, contribution_total_return: -0.2, coverage: 1, horizon_scope: 'single' },
        base: { contribution_cagr: 0.08, contribution_total_return: 0.4, coverage: 0.9, horizon_scope: 'mixed' },
    },
    expected_cagr: 0.06, expected_coverage: 1, covered_only: { scenarios: {}, expected_cagr: null }, ...over,
});
const pos = (over: Record<string, unknown> = {}) => ({
    ticker: 'ASTS', weight: 0.5, weight_scope: 'full', cagr: { bear: -0.1, base: 0.12, bull: 0.3 }, expected_cagr: 0.1,
    partial_expected_cagr: null, probability_mass: 1, price_source: 'Yahoo', price_veracity: 'OFICIAL', price_as_of: '2026-10-01',
    thesis_version: 3, model_version: null, horizon_years: 5, ...over,
});
const fc = (over: Record<string, unknown> = {}): any => ({
    as_of: '2026-10-01', base_currency: 'EUR', portfolio: portfolio(), positions: [pos()], excluded: [], assumptions: ['Supuesto 1'], ...over,
});

describe('PortfolioForecast sin agregado', () => {
    it('muestra el motivo del backend verbatim y las excluidas', () => {
        render(<PortfolioForecast forecast={fc({ portfolio: null, assumptions: ['Monedas base mezcladas'],
            excluded: [{ ticker: 'BN', weight: null, reason: 'sin FX', reason_code: 'fx' }] })} />);
        expect(screen.getByText('Monedas base mezcladas')).toBeInTheDocument();
        expect(screen.getByText(/peso N\/D \(divisa sin conversión\)/)).toBeInTheDocument();
    });

    it('sin agregado ni motivo: N/D, no inventa causa', () => {
        render(<PortfolioForecast forecast={fc({ portfolio: null, assumptions: [] })} />);
        expect(screen.getByText('N/D: no hay agregado ni motivo disponible.')).toBeInTheDocument();
    });
});

describe('PortfolioForecast sin tesis publicada', () => {
    const ex = (ticker: string, weight: number | null, code: string) => ({ ticker, weight, reason: 'r-' + ticker, reason_code: code });

    it('pide publicar la tesis de la posicion MAS pesada', () => {
        render(<PortfolioForecast forecast={fc({ portfolio: portfolio({ covered_count: 0, position_count: 3 }), positions: [],
            excluded: [ex('AAA', 0.1, 'no_published_thesis'), ex('BBB', 0.6, 'no_published_thesis'), ex('CCC', null, 'no_published_thesis')] })} />);
        expect(screen.getByRole('link', { name: 'BBB' })).toHaveAttribute('href', '/research/BBB?view=thesis');
        expect(screen.getByText(/60,0% de la cartera\) para activar/)).toBeInTheDocument();
        expect(screen.getByText(/3 de 3 posiciones sin tesis publicada vigente/)).toBeInTheDocument();
    });

    it('si todas tienen peso N/D no nombra ninguna', () => {
        render(<PortfolioForecast forecast={fc({ portfolio: portfolio({ covered_count: 0 }), positions: [], excluded: [ex('AAA', null, 'no_published_thesis')] })} />);
        expect(screen.getByText('Publica la tesis de alguna posición para activar la previsión.')).toBeInTheDocument();
    });

    it('otros motivos se cuentan aparte y se listan sin asumir causa', () => {
        render(<PortfolioForecast forecast={fc({ portfolio: portfolio({ covered_count: 0, position_count: 2 }), positions: [],
            excluded: [ex('AAA', 0.4, 'no_published_thesis'), ex('ZZZ', 0.3, 'stale_price')] })} />);
        expect(screen.getByText(/1 sin comparación verificada por otro motivo/)).toBeInTheDocument();
        expect(screen.getByText(/r-ZZZ/)).toBeInTheDocument();
        expect(screen.queryByText(/r-AAA/)).not.toBeInTheDocument();
    });

    it('con cobertura > 0 no se muestra el aviso de tesis', () => {
        render(<PortfolioForecast forecast={fc({ excluded: [ex('AAA', 0.4, 'no_published_thesis')] })} />);
        expect(screen.queryByText(/para activar la previsión/)).not.toBeInTheDocument();
    });
});

describe('PortfolioForecast con datos', () => {
    it('escenarios: signo explicito, falta de escenario es N/D, horizontes mezclados', () => {
        render(<PortfolioForecast forecast={fc()} />);
        const bear = screen.getByText('Bajista').parentElement!;
        expect(bear.textContent).toContain('-5,0%');
        expect(bear.textContent).toContain('aporte total -20,0%');
        const base = screen.getAllByText('Base')[0].parentElement!;
        expect(base.textContent).toContain('+8,0%');
        expect(base.textContent).toContain('horizontes mezclados');
        expect(base.textContent).toContain('Cobertura 90,0%');
        const bull = screen.getByText('Alcista').parentElement!;
        expect(within(bull).getAllByText('N/D').length).toBeGreaterThan(0);
        expect(bull.textContent).not.toContain('0,0%');
    });

    it('esperado del CAGR global; sin el, avisa de cobertura incompleta', () => {
        const { unmount } = render(<PortfolioForecast forecast={fc()} />);
        expect(screen.getByText('+6,0%')).toBeInTheDocument();
        expect(screen.getByText(/Media de los CAGR por escenario/)).toBeInTheDocument();
        unmount();
        render(<PortfolioForecast forecast={fc({ portfolio: portfolio({ expected_cagr: null }) })} />);
        expect(screen.getByText(/Sin cobertura completa de la cartera valorada/)).toBeInTheDocument();
    });

    it('scenarios null: los tres escenarios N/D', () => {
        render(<PortfolioForecast forecast={fc({ portfolio: portfolio({ scenarios: null }) })} />);
        expect(screen.getByText('Bajista').parentElement!.textContent).toContain('N/D');
    });

    it('fila de posicion: peso, subset valorado, parcial y N/D', () => {
        render(<PortfolioForecast forecast={fc({ positions: [
            pos({ ticker: 'AAA', weight: 0.25, weight_scope: 'valued_subset' }),
            pos({ ticker: 'BBB', expected_cagr: null, partial_expected_cagr: 0.04, probability_mass: 0.5, model_version: 2, price_veracity: 'MANUAL' }),
            pos({ ticker: 'CCC', expected_cagr: null, partial_expected_cagr: null, weight: null, cagr: { bear: null, base: null, bull: null } }),
        ] })} />);
        const row = (t: string) => screen.getByRole('link', { name: t }).closest('tr')!;
        expect(row('AAA').textContent).toContain('25,0%');
        expect(row('AAA').textContent).toContain('sobre subset valorado');
        expect(row('BBB').textContent).toContain('Parcial +4,0% · masa 50%');
        expect(row('BBB').textContent).toContain('modelo v2');
        expect(row('BBB').textContent).toContain('MANUAL');
        expect(row('CCC').textContent).not.toMatch(/\d,\d%/);
        expect(row('CCC').textContent).toContain('N/D');
    });

    it('verosimilitud no oficial se resalta distinto de OFICIAL', () => {
        render(<PortfolioForecast forecast={fc({ positions: [pos({ price_veracity: 'NO VERIFICADA' })] })} />);
        expect(screen.getByText('NO VERIFICADA').className).toContain('amber');
        expect(screen.queryByText('OFICIAL')).not.toBeInTheDocument();
    });

    it('lista excluidas con peso y supuestos', () => {
        render(<PortfolioForecast forecast={fc({ excluded: [{ ticker: 'XX', weight: 0.125, reason: 'sin tesis', reason_code: 'c' }] })} />);
        expect(screen.getByText(/12,5% de la cartera\. sin tesis/)).toBeInTheDocument();
        expect(screen.getByText('Supuesto 1')).toBeInTheDocument();
    });
});
