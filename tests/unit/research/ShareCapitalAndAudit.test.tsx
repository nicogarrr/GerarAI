import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ShareCapitalPanel } from '@/components/research/ShareCapitalPanel';
import { SourceAuditDetail, weakClaimEs } from '@/components/research/SourceAuditDetail';
import ThesisMarkdownPager from '@/components/research/ThesisMarkdownPager';
import { auditFixLabel } from '@/lib/audit-status-copy';
import { beforeEach, vi } from 'vitest';

beforeEach(() => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

const fact = (date: string, value: number, over: Record<string, unknown> = {}) => ({
    value, unit: 'shares', date, fact_id: 1, source: 'SEC 10-Q', source_url: 'https://sec.gov/a', reported_on: null, source_updated_on: null,
    status: 'OFICIAL', concept: null, previous_date: null, net_change: null, net_change_pct: null, change_status: 'SIN_DATOS', split_between_dates: false, ...over,
});
const capital = (over: Record<string, unknown> = {}) => ({ ticker: 'X', status: 'OFICIAL', as_of: '2026-10-01', share_basis: 'reported_unadjusted', series: [], annual_flows: [], ...over }) as never;

describe('ShareCapitalPanel', () => {
    it('sin saldos: N/D y mensajes explícitos (no se inventa un 0)', () => {
        render(<ShareCapitalPanel data={capital()} />);
        expect(screen.getByText('Sin saldo de acciones con fuente verificable')).toBeInTheDocument();
        expect(screen.getByText('Sin dos balances comparables')).toBeInTheDocument();
        expect(screen.getByText(/No hay saldos de acciones con fuente verificable/)).toBeInTheDocument();
        expect(screen.getAllByText('N/D').length).toBeGreaterThan(0);
    });
    it('cambio neto: positivo con signo +, negativo con signo menos', () => {
        const up = { series: [fact('2025-06-30', 100), fact('2026-06-30', 110, { previous_date: '2025-06-30', net_change_pct: 10, change_status: 'DERIVADO' })] };
        const { unmount } = render(<ShareCapitalPanel data={capital(up)} />);
        expect(screen.getAllByText('+10,00%').length).toBeGreaterThan(0);
        unmount();
        const down = { series: [fact('2025-06-30', 100), fact('2026-06-30', 95, { previous_date: '2025-06-30', net_change_pct: -5, change_status: 'DERIVADO' })] };
        render(<ShareCapitalPanel data={capital(down)} />);
        expect(screen.getAllByText('-5,00%').length).toBeGreaterThan(0);
    });
    it('un split entre fechas o un salto brusco NO se presenta como emisión/recompra', () => {
        const split = { series: [fact('2025-06-30', 100), fact('2026-06-30', 400, { previous_date: '2025-06-30', split_between_dates: true })] };
        const { unmount } = render(<ShareCapitalPanel data={capital(split)} />);
        expect(screen.getAllByText(/Split/).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/no comparable/).length).toBeGreaterThan(0);
        unmount();
        const jump = { series: [fact('2025-06-30', 100), fact('2026-06-30', 900, { previous_date: '2025-06-30', abrupt_jump: true })] };
        render(<ShareCapitalPanel data={capital(jump)} />);
        expect(screen.getAllByText(/posible split no registrado/).length).toBeGreaterThan(0);
    });
    it('enlaza cada cifra con su fuente en pestaña nueva y segura', () => {
        render(<ShareCapitalPanel data={capital({ series: [fact('2026-06-30', 100, { reported_on: '2026-08-01' })] })} />);
        const link = screen.getAllByRole('link')[0];
        expect(link).toHaveAttribute('href', 'https://sec.gov/a');
        expect(link).toHaveAttribute('rel', 'noopener noreferrer');
        expect(link).toHaveAttribute('target', '_blank');
        expect(link.textContent).toMatch(/SEC 10-Q · .*Presentado/);
    });
    it('pestaña de emisiones y recompras: celdas sin dato salen N/D, con unidad si no son acciones', () => {
        const flows = [{ date: '2025-12-31', common_stock_repurchased: fact('2025-12-31', 5, { unit: 'USD' }) }];
        render(<ShareCapitalPanel data={capital({ series: [fact('2026-06-30', 100)], annual_flows: flows })} />);
        fireEvent.click(screen.getByRole('button', { name: 'Emisiones y recompras anuales' }));
        const table = screen.getByRole('table');
        expect(within(table).getByText(/5 USD/)).toBeInTheDocument();
        expect(within(table).getAllByText('N/D')).toHaveLength(3);
    });
    it('flujos vacíos: mensaje propio', () => {
        render(<ShareCapitalPanel data={capital({ series: [fact('2026-06-30', 100)] })} />);
        fireEvent.click(screen.getByRole('button', { name: 'Emisiones y recompras anuales' }));
        expect(screen.getByText(/No hay flujos anuales con fuente verificable/)).toBeInTheDocument();
    });
    it('paginación de 10 en 10: más reciente primero, límites deshabilitados, vuelve a la 1 al cambiar de pestaña', () => {
        const series = Array.from({ length: 12 }, (_, i) => fact(`20${String(10 + i)}-06-30`, 100 + i));
        render(<ShareCapitalPanel data={capital({ series })} />);
        expect(screen.getAllByText('1 / 2')).toHaveLength(2);
        expect(screen.getAllByRole('button', { name: 'Anterior' })[0]).toBeDisabled();
        expect(screen.getAllByRole('row')).toHaveLength(1 + 10);
        fireEvent.click(screen.getAllByRole('button', { name: 'Siguiente' })[0]);
        expect(screen.getAllByText('2 / 2')).toHaveLength(2);
        expect(screen.getAllByRole('row')).toHaveLength(1 + 2);
        expect(screen.getAllByRole('button', { name: 'Siguiente' })[0]).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Saldos' }));
        expect(screen.getAllByText('1 / 2')).toHaveLength(2);
    });
});

const audit = (over: Record<string, unknown> = {}) => ({
    passed: false, created_at: '2026-10-01T10:00:00Z', thesis_version: 3, required_fixes: [], unsupported_claims: [], data_conflicts: [], weak_claims: [], ...over,
}) as never;

describe('SourceAuditDetail', () => {
    it('enlace a la tesis con versión y ticker codificado', () => {
        render(<SourceAuditDetail audit={audit()} ticker="BRK/B" />);
        expect(screen.getByRole('link', { name: 'Ver tesis v3' })).toHaveAttribute('href', '/research/BRK%2FB?view=thesis');
        render(<SourceAuditDetail audit={audit({ thesis_version: null })} ticker="X" />);
        expect(screen.getByRole('link', { name: 'Ver tesis' })).toBeInTheDocument();
    });
    it('auditoría bloqueada sin ningún motivo: lo dice en vez de callar', () => {
        render(<SourceAuditDetail audit={audit()} ticker="X" />);
        expect(screen.getByText(/Motivo del bloqueo no registrado/)).toBeInTheDocument();
    });
    it('bloqueada solo por baja confianza: lo explica y traduce la frase conocida', () => {
        render(<SourceAuditDetail audit={audit({ weak_claims: ['SEC/FMP reconciliation missing for reported financial facts.', 'Otra'] })} ticker="X" />);
        expect(screen.getByText(/Bloqueada por afirmaciones de baja confianza/)).toBeInTheDocument();
        expect(screen.getByText('Falta conciliar con SEC/FMP las cifras financieras reportadas.')).toBeInTheDocument();
        expect(screen.getByText('Otra')).toBeInTheDocument();
        // La conciliación ausente descuenta 5 puntos pero no es baja confianza:
        // va con su propio título para que la puntuación sea explicable.
        expect(screen.getByText('Conciliación SEC/FMP (1)')).toBeInTheDocument();
        expect(screen.getByText('Baja confianza (1)')).toBeInTheDocument();
    });
    it('una auditoría superada no muestra motivo de bloqueo', () => {
        render(<SourceAuditDetail audit={audit({ passed: true })} ticker="X" />);
        expect(screen.queryByText(/Motivo del bloqueo/)).toBeNull();
        expect(screen.queryByText(/Bloqueada/)).toBeNull();
    });
    it('listas largas: muestra 5 y cuenta el resto', () => {
        const items = Array.from({ length: 8 }, (_, i) => `claim ${i}`);
        render(<SourceAuditDetail audit={audit({ unsupported_claims: items })} ticker="X" />);
        expect(screen.getByText('Afirmaciones sin fuente (8)')).toBeInTheDocument();
        expect(screen.getAllByText(/^claim /)).toHaveLength(5);
        expect(screen.getByText('y 3 más')).toBeInTheDocument();
        expect(screen.queryByText(/Motivo del bloqueo/)).toBeNull();
    });
    it('weakClaimEs solo cambia la frase conocida', () => {
        expect(weakClaimEs('  sec/fmp reconciliation missing for reported financial facts  ')).toMatch(/^Falta conciliar/);
        expect(weakClaimEs('otra cosa')).toBe('otra cosa');
    });
});

describe('auditFixLabel', () => {
    it('claves técnicas pasan a etiquetas legibles', () => {
        expect(auditFixLabel('Missing valuation inputs: market_cap.')).toMatch(/^Faltan entradas de valoración: Capitalización bursátil/);
        expect(auditFixLabel('falta algo_raro_x')).toBe('falta algo raro x');
        expect(auditFixLabel('Texto normal')).toBe('Texto normal');
    });
});

describe('ThesisMarkdownPager', () => {
    const pages = [{ id: 'p0', title: 'Resumen', body: '## Resumen\nTexto uno' }, { id: 'p1', title: 'Riesgos', body: '## Riesgos\nTexto dos' }, { id: 'p2', title: 'Fin', body: '## Fin\nTexto tres' }];
    it('sin páginas no pinta nada', () => {
        expect(render(<ThesisMarkdownPager pages={[]} />).container).toBeEmptyDOMElement();
    });
    // El visor markdown carga diferido (chunk propio): el texto llega asíncrono.
    it('navega con anterior/siguiente y selector; límites deshabilitados', async () => {
        render(<ThesisMarkdownPager pages={pages} />);
        expect(await screen.findByText('Texto uno')).toBeInTheDocument();
        expect(screen.getByText('1/3')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Sección anterior' })).toBeDisabled();
        fireEvent.click(screen.getAllByRole('button', { name: 'Siguiente' })[0]);
        expect(await screen.findByText('Texto dos')).toBeInTheDocument();
        fireEvent.change(screen.getByRole('combobox', { name: 'Sección del memorando' }), { target: { value: '2' } });
        expect(await screen.findByText('Texto tres')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Sección siguiente' })).toBeDisabled();
        expect(screen.getByText('3/3')).toBeInTheDocument();
    });
    it('si el inicio ya salió de la vista al cambiar de página, vuelve a colocarlo', () => {
        const { container } = render(<ThesisMarkdownPager pages={pages} />);
        const top = container.firstElementChild as HTMLElement;
        top.getBoundingClientRect = () => ({ top: -50 }) as DOMRect;
        const spy = vi.fn();
        top.scrollIntoView = spy;
        fireEvent.click(screen.getAllByRole('button', { name: 'Siguiente' })[0]);
        expect(spy).toHaveBeenCalledWith({ block: 'start' });
        spy.mockClear();
        top.getBoundingClientRect = () => ({ top: 10 }) as DOMRect;
        fireEvent.click(screen.getAllByRole('button', { name: 'Anterior' })[0]);
        expect(spy).not.toHaveBeenCalled();
    });
});
