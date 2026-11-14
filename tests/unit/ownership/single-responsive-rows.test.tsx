import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { mobileHoldings, mobileChanges } from '../../fixtures/ownership-mobile';

// /ownership pintaba DOS árboles completos por fila: tarjetas móvil
// (`md:hidden`, role article) y tabla escritorio (`hidden md:block`), tanto en
// participaciones como en movimientos. Los 13F de un gestor grande llevan
// cientos de filas duplicadas en el HTML/RSC. Contrato (decisión de diseño,
// 2026-11-14): UNA tabla responsiva por sección (patrón PositionsTable /
// /watchlist: fila tarjeta debajo de md, fila de tabla desde md) con el mismo
// contenido en cada viewport: una participación = una fila, un movimiento = una fila.
const mocks = vi.hoisted(() => ({ locale: 'es', managers: vi.fn(), holdings: vi.fn(), changes: vi.fn() }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('@/lib/actions/ownership.actions', () => ({ getOwnershipManagers: mocks.managers, getManagerHoldings: mocks.holdings, getManagerChanges: mocks.changes }));
vi.mock('@/app/(root)/ownership/SyncButton', () => ({ default: () => null }));
vi.mock('@/app/(root)/inversores/_components/SyncPortfoliosButton', () => ({ SyncPortfoliosButton: () => null }));
vi.mock('@/app/(root)/ownership/_components/MostBought', () => ({ MostBought: () => <p>Most bought fixture</p> }));
vi.mock('@/app/(root)/ownership/_components/Overlap', () => ({ Overlap: () => <p>Overlap fixture</p> }));
import OwnershipPage from '@/app/(root)/ownership/page';

beforeEach(() => {
    mocks.locale = 'es';
    mocks.managers.mockReset().mockResolvedValue({ managers: [{ cik: '1', name: 'Fixture Fund' }], limitations: [] });
    mocks.holdings.mockReset().mockResolvedValue(structuredClone(mobileHoldings));
    mocks.changes.mockReset().mockResolvedValue(structuredClone(mobileChanges));
});

const dataRows = () =>
    screen.queryAllByRole('row').filter((row) => row.getAttribute('aria-label')?.startsWith('LONG ISSUER'));

it('una participación = una fila (sin árbol duplicado móvil/escritorio)', async () => {
    render(await OwnershipPage({ searchParams: Promise.resolve({}) }));
    // No quedan tarjetas <article>: cada fila vive una sola vez, como <tr>.
    expect(screen.queryByRole('article')).toBeNull();
    // 1 participación + 1 movimiento = 2 filas de datos (antes: 2 artículos + 2 <tr>).
    expect(dataRows()).toHaveLength(2);
});

it('la fila única conserva etiquetas móviles, distintivos y enlace al filing', async () => {
    render(await OwnershipPage({ searchParams: Promise.resolve({}) }));
    const holding = dataRows()[0];
    // Etiquetas que en móvil acompañan a cada valor (visibles < md, ocultas >= md).
    expect(within(holding).getByText('CUSIP')).toBeInTheDocument();
    expect(within(holding).getByText('123456789')).toBeInTheDocument();
    expect(within(holding).getByText('CLASS A COMMON STOCK')).toBeInTheDocument();
    expect(within(holding).getByText(/enmienda/)).toBeInTheDocument();
    expect(within(holding).getByRole('link', { name: /XML/ })).toHaveAttribute('href', 'https://example.com/fixture-13f.xml');
    const change = dataRows()[1];
    expect(within(change).getByText(/aumentada/)).toBeInTheDocument();
});
