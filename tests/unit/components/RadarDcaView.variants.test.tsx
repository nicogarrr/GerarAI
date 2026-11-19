import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RadarDcaOpportunity, RadarDcaResult } from '@/lib/actions/propicks-radar-dca.actions';

vi.mock('@/lib/actions/propicks-radar-dca.actions', () => ({ getRadarDcaOpportunities: vi.fn() }));
import { getRadarDcaOpportunities } from '@/lib/actions/propicks-radar-dca.actions';
import RadarDcaView from '@/components/proPicks/RadarDcaView';

const mockGet = vi.mocked(getRadarDcaOpportunities);

const baseItem: RadarDcaOpportunity = {
    ticker: 'BASE', name: null, sector: null, currency: 'USD',
    level: 2, level_label: '2X DCA', status: 'forming', signal_date: null,
    close: null, price_date: null, source: 'yfinance', price_verified: true,
    confirmed_level: null, confirmed_period: null, clear_price_signal: false,
    change: { status: 'no_baseline', changed: null },
    formula_version: 'nico-v1', scan_date: '2026-10-30',
    quality: { passed: false, reasons: [], policy: 'quality-v1', market_cap_usd: null },
};

const resultOf = (items: RadarDcaOpportunity[], over: Partial<RadarDcaResult> = {}): RadarDcaResult => ({
    as_of: '2026-10-31', page: 1, page_size: 20, total: items.length, has_more: false,
    sectors: ['Technology'], counts_by_level: {}, coverage: { universe: 27, evaluated: 26, ok: 25, invalid: 1, stale: 0 },
    items, ...over,
});

describe('RadarDcaView: variantes de tarjeta y filtros', () => {
    beforeEach(() => {
        mockGet.mockReset();
        mockGet.mockResolvedValue(resultOf([baseItem]));
    });

    it('tarjeta mínima: sin nombre, sector, cierre ni fecha de señal no se inventa nada', async () => {
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('BASE')).toBeInTheDocument());
        expect(screen.queryByText(/Cierre/)).not.toBeInTheDocument();
        expect(screen.queryByText(/señal/)).not.toBeInTheDocument();
    });

    it('sin nivel no hay badge; nivel fuera de escala cae al estilo 1X', async () => {
        mockGet.mockResolvedValue(resultOf([
            { ...baseItem, ticker: 'NONULL', level: null, level_label: null },
            { ...baseItem, ticker: 'ODD', level: 99, level_label: null },
        ]));
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('ODD')).toBeInTheDocument());
        expect(screen.getByText('99X DCA')).toBeInTheDocument();
    });

    it('recorte sin etiqueta del backend: fallback RECORTE', async () => {
        mockGet.mockResolvedValue(resultOf([{ ...baseItem, ticker: 'TRIM2', level: -2, level_label: null }]));
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('RECORTE')).toBeInTheDocument());
    });

    it('confirmado sin periodo: no se pinta una línea coja de último confirmado', async () => {
        mockGet.mockResolvedValue(resultOf([{ ...baseItem, confirmed_level: 2, confirmed_period: null }]));
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('BASE')).toBeInTheDocument());
        expect(screen.queryByText(/Último confirmado/)).not.toBeInTheDocument();
    });

    it('cambio sin fecha ni niveles: marcadores — en vez de huecos', async () => {
        mockGet.mockResolvedValue(resultOf([
            { ...baseItem, change: { status: 'compared', changed: true, from_level: null, to_level: null, since_price_date: null } },
        ]));
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('Cambio —X → —X')).toBeInTheDocument());
    });

    it('filtro de sector y fuera de cartera llegan a la acción y resetean la página', async () => {
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('BASE')).toBeInTheDocument());
        fireEvent.change(screen.getByRole('combobox', { name: 'Sector' }), { target: { value: 'Technology' } });
        await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith(
            { page: 1, level: null, sector: 'Technology', outsideTracked: false, qualityClear: false },
        ));
        fireEvent.click(screen.getByRole('checkbox', { name: 'Fuera de cartera y watchlist' }));
        await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith(
            { page: 1, level: null, sector: 'Technology', outsideTracked: true, qualityClear: false },
        ));
    });

    it('Anterior vuelve de la página 2 a la 1', async () => {
        mockGet.mockResolvedValue(resultOf([baseItem], { has_more: true, total: 40 }));
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('BASE')).toBeInTheDocument());
        fireEvent.click(screen.getByRole('button', { name: /Siguiente/ }));
        await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith(
            { page: 2, level: null, sector: null, outsideTracked: false, qualityClear: false },
        ));
        fireEvent.click(screen.getByRole('button', { name: /Anterior/ }));
        await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith(
            { page: 1, level: null, sector: null, outsideTracked: false, qualityClear: false },
        ));
    });
});
