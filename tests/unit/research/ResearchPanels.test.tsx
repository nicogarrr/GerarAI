import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OwnershipSignalsPanel } from '@/components/research/OwnershipSignalsPanel';
import { TtmPanel } from '@/components/research/TtmPanel';
import { ThesisScenariosPanel } from '@/components/research/ThesisScenariosPanel';
import type { OwnershipSignals } from '@/lib/research/ownership-signals';
import type { ResearchTtm } from '@/lib/research/ttm-display';

beforeEach(() => {
    // Panel (collapsible) lee matchMedia; jsdom no lo trae. matches:false = móvil.
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

const side = { trades: 0, insiders: 0, shares: 0, value: 0 };

describe('OwnershipSignalsPanel', () => {
    it('sin datos del servidor dice que no pudo cargar, sin cifras', () => {
        render(<OwnershipSignalsPanel ticker="AAPL" signals={null} />);
        expect(screen.getByText(/No se pudo cargar el resumen/)).toBeInTheDocument();
        expect(screen.queryByText(/Fuente: SEC EDGAR/)).toBeNull();
    });
    it('sin datos (sin_datos/pendiente) muestra el motivo y no pinta insignias ni ceros', () => {
        const signals: OwnershipSignals = { ticker: 'X', insider: { status: 'sin_datos', detail: 'Sin Form 4 sincronizados' }, holders: { status: 'pendiente' } };
        render(<OwnershipSignalsPanel ticker="X" signals={signals} />);
        expect(screen.getByText('Sin Form 4 sincronizados')).toBeInTheDocument();
        expect(screen.getByText('Sin datos 13F.')).toBeInTheDocument();
        expect(screen.queryByText(/gestores$/)).toBeNull();
    });
    it('con datos: lectura de insiders, nº de gestores, cambios por gestor y enlace con ticker codificado', () => {
        const signals: OwnershipSignals = {
            ticker: 'BRK/B',
            insider: { status: 'ok', window_days: 90, source: 'sec', buys: { ...side, trades: 2, insiders: 1, value: 1000 }, sells: side, net_value: 1000, cluster_buying: false, last_date: null, reading: 'Compras netas' },
            holders: { status: 'ok', source: '13f', holders_count: 4, managers_with_data: 20, report_date: '2026-06-30', total_value_usd: null, changes: { new: 1, increased: 0, decreased: 0, closed: 0 },
                top_holders: [{ name: 'Fondo A', value_usd: 5000, change: 'new' }, { name: 'Fondo B', value_usd: null, change: null }], exited: [], limitations: [] },
        };
        render(<OwnershipSignalsPanel ticker="BRK/B" signals={signals} />);
        expect(screen.getByText('Compras netas')).toBeInTheDocument();
        expect(screen.getByText(/· 90 días/)).toBeInTheDocument();
        expect(screen.getByText('4 gestores')).toBeInTheDocument();
        expect(screen.getByText(/Fondo A: .* \(nueva posición\)/)).toBeInTheDocument();
        expect(screen.getByText('Fondo B (sin comparación)')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Ver propietarios' })).toHaveAttribute('href', '/research/BRK%2FB?view=holders');
    });
});

const ttm = (metrics: ResearchTtm['metrics']): ResearchTtm => ({ ticker: 'X', as_of: null, formula: 'TTM = suma de 4 trimestres', metrics });

describe('TtmPanel', () => {
    it('sin datos explica cómo conseguirlos y no muestra tarjetas', () => {
        render(<TtmPanel ttm={null} />);
        expect(screen.getByText(/Sin trimestres ni ejercicios guardados/)).toBeInTheDocument();
        render(<TtmPanel ttm={ttm([{ metric: 'revenue', value: null, unit: 'USD', basis: 'SIN_DATOS', label: '', provenance: 'SIN_DATOS', period_end: null }])} />);
        expect(screen.getAllByText(/Sin trimestres/)).toHaveLength(2);
    });
    it('muestra valor con su unidad, base, procedencia y trimestres inferidos; un valor nulo sale N/D', () => {
        render(<TtmPanel ttm={ttm([
            { metric: 'revenue', value: 12.5, unit: 'EUR', basis: 'TTM', label: 'x', provenance: 'INFERIDO', period_end: '2026-06-30', note: 'Q4 inferido',
              quarters: [{ period_end: '2025-12-31', value: 1, reported: false, origin: 'FY-9M' }] },
            { metric: 'net_income', value: null, unit: 'USD', basis: 'FY', label: 'x', provenance: 'SIN_DATOS', period_end: null },
        ])} />);
        expect(screen.getByText('12,50 €')).toBeInTheDocument();
        expect(screen.getByText('INFERIDO')).toBeInTheDocument();
        expect(screen.getByText(/hasta 30\/06\/2026/)).toBeInTheDocument();
        expect(screen.getByText(/Q4 = FY − 9 meses, inferido/)).toBeInTheDocument();
        expect(screen.getByText('Q4 inferido')).toBeInTheDocument();
        expect(screen.getByText('N/D')).toBeInTheDocument();
        expect(screen.getByText('Sin datos')).toBeInTheDocument();
        expect(screen.getByText('TTM = suma de 4 trimestres')).toBeInTheDocument();
    });
});

const proj = (ejercicio: number, v: number | null, extra: Record<string, unknown> = {}) => ({
    ejercicio,
    ingresos: { valor: v, etiqueta: 'INFERIDO', motivo: null, ...extra },
    fcf: { valor: null, etiqueta: 'SIN_DATOS', motivo: null },
    bps: { valor: null, etiqueta: 'INFERIDO', motivo: null },
});
const scenarios = (over: Record<string, unknown> = {}) => ({
    estado: 'persistido',
    escenarios: {
        bear: { nombre: 'Pesimista', proyecciones: [proj(2027, 100)] },
        base: { nombre: 'Base', proyecciones: [proj(2027, 200), proj(2028, null, { motivo: 'Sin dato de ingresos' })] },
        bull: { nombre: 'Optimista', proyecciones: [proj(2027, 300)] },
    },
    aviso_coherencia: null,
    fuente: { modelo: 'DCF', version: 3, fecha: '2026-10-01' },
    ...over,
}) as never;

describe('ThesisScenariosPanel', () => {
    it('no se pinta si no hay escenarios persistidos', () => {
        const { container } = render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={null} />);
        expect(container).toBeEmptyDOMElement();
        const second = render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={scenarios({ estado: 'pendiente' })} />);
        expect(second.container).toBeEmptyDOMElement();
    });
    it('sin ejercicios proyectados tampoco', () => {
        const empty = scenarios({ escenarios: { bear: { nombre: 'a', proyecciones: [] }, base: { nombre: 'b', proyecciones: [] }, bull: { nombre: 'c', proyecciones: [] } } });
        expect(render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={empty} />).container).toBeEmptyDOMElement();
    });
    it('importes en la divisa declarada, N/D sin dato, y el motivo se anuncia al lector de pantalla', () => {
        render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={scenarios()} />);
        const table = screen.getAllByRole('table')[0];
        expect(within(table).getByText('100,0 US$')).toBeInTheDocument();
        expect(within(table).getByText('300,0 US$')).toBeInTheDocument();
        expect(within(table).getByText(/Sin dato de ingresos/)).toBeInTheDocument();
        expect(screen.getByText(/Proyección del modelo DCF v3, corte 2026-10-01/)).toBeInTheDocument();
    });
    it('ADR o divisa desconocida: NO se muestra un importe con divisa inventada, y se avisa', () => {
        render(<ThesisScenariosPanel adrRatio={2} currency="USD" data={scenarios()} />);
        expect(screen.queryByText('100,0 US$')).toBeNull();
        expect(screen.getAllByText(/Divisa del emisor no verificada/).length).toBeGreaterThan(0);
    });
    it('aviso de coherencia se muestra', () => {
        render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={scenarios({ aviso_coherencia: 'Escenarios incoherentes' })} />);
        expect(screen.getByText('Escenarios incoherentes')).toBeInTheDocument();
    });
});

