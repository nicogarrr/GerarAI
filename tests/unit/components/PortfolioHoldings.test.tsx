import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const h = vi.hoisted(() => ({
    del: vi.fn(), refreshPrices: vi.fn(), routerRefresh: vi.fn(),
    success: vi.fn(), error: vi.fn(), info: vi.fn(), showError: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.routerRefresh }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteHolding: h.del, refreshPortfolioHoldings: h.refreshPrices }));
vi.mock('sonner', () => ({ toast: { success: h.success, error: h.error, info: h.info } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: h.showError }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: () => null }));
vi.mock('@/components/common/TrackedAnalysisStatus', () => ({ TrackedAnalysisStatus: () => null }));
vi.mock('@/components/common/ExtendedHoursLine', () => ({ default: () => null }));
vi.mock('@/components/common/AnalystTargetLine', () => ({ default: () => null }));
vi.mock('@/components/portfolio/HoldingSignals', () => ({
    DcaLevelChip: () => null, FairValueLine: () => null, useHoldingSignals: () => null,
}));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => <span>import-ibkr</span> }));
vi.mock('@/components/portfolio/ImportImageButton', () => ({ default: () => <span>import-image</span> }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => <span>add-tx</span> }));
import PortfolioHoldings from '@/components/portfolio/PortfolioHoldings';

function holding(over: Record<string, unknown> = {}) {
    return {
        symbol: 'AAPL', quantity: 10, avgPrice: 100, currentPrice: 120, valuationHold: null,
        value: 1200, cost: 1000, gain: 200, gainPercent: 20, nativeCurrency: 'EUR', baseCurrency: 'EUR',
        fxMissing: false, nativeGain: null, nativeCost: null, valueMissing: false,
        firstBuyDate: '2024-01-15', holdingDays: 400, fiscalBucket: 'largo_plazo', ...over,
    } as any;
}
const desktop = () => within(screen.getByRole('table'));

describe('PortfolioHoldings estados y numeros', () => {
    it('IBKR en revisión muestra aviso, promedio N/D y conserva el valor', () => {
        render(<PortfolioHoldings holdings={[holding({ avgPrice: 0, cost: 0, gain: 0, fxMissing: true, costReviewMessage: 'Coste pendiente de revisión: IBKR' })]} userId="u" />);
        const row = desktop().getByText('AAPL').closest('tr')!;
        expect(row.textContent).toContain('Coste pendiente de revisión');
        expect(row.querySelectorAll('td')[2].textContent).toContain('N/D');
        expect(row.querySelectorAll('td')[4].textContent).toMatch(/1\.?200/);
        expect(screen.getAllByRole('status').length).toBe(2);
    });
    beforeEach(() => vi.clearAllMocks());

    it('sin posiciones ni caja: mensaje vacio y boton de actualizar desactivado', () => {
        render(<PortfolioHoldings holdings={[]} userId="u" />);
        expect(screen.getByText('No tienes posiciones abiertas')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Actualizar precios/ })).toBeDisabled();
    });

    it('solo caja: se muestra la fila Caja con su importe y N/D en peso y G/P', () => {
        render(<PortfolioHoldings holdings={[]} userId="u" cash={1500} baseCurrency="EUR" />);
        const row = desktop().getByText('Caja').closest('tr')!;
        expect(row.textContent).toMatch(/1\.?500/);
        expect(row.textContent).toContain('N/D');
    });

    it('cantidad fraccionaria: hasta 4 decimales (no «0,00» para 0,004 acciones) y entera sin decimales', () => {
        render(<PortfolioHoldings holdings={[holding({ symbol: 'FRAC', quantity: 0.0042 }), holding({ symbol: 'MSFT', quantity: 12 })]} userId="u" />);
        const frac = desktop().getByText('FRAC').closest('tr')!;
        expect(frac.querySelectorAll('td')[1].textContent).toBe('0,0042');
        const whole = desktop().getByText('MSFT').closest('tr')!;
        expect(whole.querySelectorAll('td')[1].textContent).toBe('12');
    });

    it('caja 0 o null no pinta fila de caja', () => {
        render(<PortfolioHoldings holdings={[holding()]} userId="u" cash={0} />);
        expect(desktop().queryByText('Caja')).not.toBeInTheDocument();
    });

    it('ganancia positiva, peso 100 % con una sola posicion y fiscal largo plazo', () => {
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        const row = desktop().getByText('AAPL').closest('tr')!;
        expect(row.textContent).toMatch(/200/);
        expect(row.textContent).toMatch(/\+20,00\s?%/);
        expect(row.textContent).toMatch(/100,0\s?%/);
        expect(row.textContent).toContain('Largo plazo · 400d');
    });

    it('perdida: sin signo falso de ganancia', () => {
        render(<PortfolioHoldings holdings={[holding({ gain: -50, gainPercent: -5, value: 950 })]} userId="u" />);
        const row = desktop().getByText('AAPL').closest('tr')!;
        expect(row.textContent).toMatch(/-\s?50|−\s?50/);
        expect(row.textContent).not.toMatch(/\+5,00/);
    });

    it('sin tipo de cambio la G/P es N/D, no una cifra', () => {
        render(<PortfolioHoldings holdings={[holding({ fxMissing: true })]} userId="u" />);
        const row = desktop().getByText('AAPL').closest('tr')!;
        expect(row.textContent).not.toMatch(/\+20,00/);
        expect(row.textContent).toContain('N/D');
    });

    it('coste 0: G/P desconocida (no divide ni inventa)', () => {
        render(<PortfolioHoldings holdings={[holding({ cost: 0, gain: 1200, gainPercent: 0 })]} userId="u" />);
        const row = desktop().getByText('AAPL').closest('tr')!;
        expect(row.textContent).not.toMatch(/\+\d/);
        expect(row.textContent).toContain('N/D');
    });

    it('precio actual null: N/D; precio medio 0: N/D', () => {
        render(<PortfolioHoldings holdings={[holding({ currentPrice: null, avgPrice: 0 })]} userId="u" />);
        const cells = desktop().getByText('AAPL').closest('tr')!.querySelectorAll('td');
        expect(cells[2].textContent).toBe('N/D');
        expect(cells[3].textContent).toContain('N/D');
    });

    it('sin historial de compra, fiscal N/D', () => {
        render(<PortfolioHoldings holdings={[holding({ fiscalBucket: null, holdingDays: null, firstBuyDate: null })]} userId="u" />);
        expect(screen.getAllByText(/Fiscal: N\/D|^N\/D$/).length).toBeGreaterThan(0);
    });

    it('corto plazo sin dias no pinta dias', () => {
        render(<PortfolioHoldings holdings={[holding({ fiscalBucket: 'corto_plazo', holdingDays: null })]} userId="u" />);
        expect(screen.getAllByText('Corto plazo').length).toBeGreaterThan(0);
    });

    it('divisa nativa distinta: G/P nativa si contradice y efecto precio/divisa', () => {
        render(<PortfolioHoldings holdings={[holding({
            nativeCurrency: 'USD', priceEffect: 300, fxEffect: -100, gain: 200, nativeGain: -20, nativeCost: 1000,
        })]} userId="u" />);
        expect(screen.getAllByText(/Precio .* · Divisa/).length).toBeGreaterThan(0);
    });

    it('el peso excluye posiciones sin valorar', () => {
        render(<PortfolioHoldings holdings={[
            holding({ symbol: 'AAA', value: 100 }),
            holding({ symbol: 'BBB', value: 300 }),
            holding({ symbol: 'CCC', value: 0, valueMissing: true }),
        ]} userId="u" />);
        const w = (s: string) => desktop().getByText(s).closest('tr')!.textContent!;
        expect(w('AAA')).toMatch(/25,0\s?%/);
        expect(w('BBB')).toMatch(/75,0\s?%/);
        expect(w('CCC')).toContain('N/D');
    });
});

describe('PortfolioHoldings eliminar', () => {
    beforeEach(() => vi.clearAllMocks());

    it('pide confirmacion y no borra si se cancela', () => {
        render(<PortfolioHoldings holdings={[holding()]} userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar posición en AAPL' }));
        expect(screen.getByText(/Se borrarán todas las operaciones de AAPL: compras, ventas y dividendos, también los de años ya declarados/)).toBeInTheDocument();
        expect(screen.getByText(/registra la venta en lugar de borrarla/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        expect(h.del).not.toHaveBeenCalled();
    });

    it('confirmado: borra con el usuario correcto y refresca', async () => {
        h.del.mockResolvedValue(undefined);
        render(<PortfolioHoldings holdings={[holding()]} userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar posición en AAPL' }));
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar todo el historial' }));
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('Posición AAPL eliminada'));
        expect(h.del).toHaveBeenCalledWith('u1', 'AAPL');
        expect(h.routerRefresh).toHaveBeenCalled();
    });

    it('fallo al borrar: toast de error y sin exito', async () => {
        h.del.mockRejectedValue(new Error('x'));
        render(<PortfolioHoldings holdings={[holding()]} userId="u1" />);
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar posición en AAPL' }));
        fireEvent.click(screen.getByRole('button', { name: 'Eliminar todo el historial' }));
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
        expect(h.success).not.toHaveBeenCalled();
    });
});

describe('PortfolioHoldings actualizar precios (el toast dice lo que se escribio)', () => {
    beforeEach(() => vi.clearAllMocks());
    const click = () => fireEvent.click(screen.getByRole('button', { name: /Actualizar precios/ }));
    const base = { ok: true, updated: ['AAPL'], skipped: [] as string[], failed: [] as string[], holdings: [holding()] };

    it('ok=false: error "Ningun precio escrito" con causas, sin toast verde', async () => {
        h.refreshPrices.mockResolvedValue({ ok: false, updated: [], skipped: ['A', 'B'], failed: ['C'] });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.error).toHaveBeenCalledWith('Ningún precio escrito (sin cotización: A, B; escritura fallida: C)'));
        expect(h.success).not.toHaveBeenCalled();
    });

    it('ok=false sin detalle', async () => {
        h.refreshPrices.mockResolvedValue({ ok: false, updated: [], skipped: [], failed: [] });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.error).toHaveBeenCalledWith('Ningún precio escrito (sin detalle)'));
    });

    it('lista de simbolos larga se acorta a 5 y cuenta el resto', async () => {
        h.refreshPrices.mockResolvedValue({ ok: false, updated: [], skipped: ['A', 'B', 'C', 'D', 'E', 'F', 'G'], failed: [] });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.error).toHaveBeenCalledWith(expect.stringContaining('A, B, C, D, E y 2 más')));
    });

    it('parcial con escrituras fallidas y relectura fallida lo declara', async () => {
        h.refreshPrices.mockResolvedValue({ ...base, updated: ['A'], failed: ['B'], holdingsStale: true });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.error).toHaveBeenCalledWith('1 de 2 precios guardados; escritura fallida: B; y no se pudo releer la cartera (recarga la página)'));
    });

    it('precios guardados pero relectura fallida: aviso informativo', async () => {
        h.refreshPrices.mockResolvedValue({ ...base, holdingsStale: true });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.info).toHaveBeenCalledWith(expect.stringContaining('Precios guardados; no se pudo releer')));
        expect(h.success).not.toHaveBeenCalled();
    });

    it('parcial con simbolos sin cotizacion: cuenta x de y', async () => {
        h.refreshPrices.mockResolvedValue({ ...base, updated: ['A', 'B'], skipped: ['C'] });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.info).toHaveBeenCalledWith('2 de 3 precios actualizados; sin cotización: C'));
    });

    it('exito: singular y plural', async () => {
        h.refreshPrices.mockResolvedValueOnce(base);
        const { unmount } = render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('1 precio actualizado'));
        unmount();
        h.refreshPrices.mockResolvedValueOnce({ ...base, updated: ['A', 'B'] });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.success).toHaveBeenCalledWith('2 precios actualizados'));
    });

    it('excepcion: toast de error', async () => {
        h.refreshPrices.mockRejectedValue(new Error('net'));
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(h.showError).toHaveBeenCalled());
    });

    it('tras actualizar se muestran las posiciones releidas', async () => {
        h.refreshPrices.mockResolvedValue({ ...base, holdings: [holding({ symbol: 'NEWCO' })] });
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        click();
        await waitFor(() => expect(desktop().getByText('NEWCO')).toBeInTheDocument());
    });
});

describe('PortfolioHoldings cabecera', () => {
    it('el título de la tarjeta es solo «Posiciones actuales» y la nota de divisa va aparte', () => {
        render(<PortfolioHoldings holdings={[holding()]} userId="u" baseCurrency="EUR" />);
        // Antes la nota larga vivía DENTRO del <h3>: el lector de pantalla
        // anunciaba un título de 30 palabras y en móvil se apretujaba al lado.
        const heading = screen.getByRole('heading', { name: 'Posiciones actuales' });
        const note = screen.getByText(/La G\/P va en EUR \(divisa base\)/);
        expect(heading).not.toContainElement(note);
        expect(note.tagName).toBe('P');
    });
});
