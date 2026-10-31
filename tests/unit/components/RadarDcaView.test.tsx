import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RadarDcaResult } from '@/lib/actions/propicks-radar-dca.actions';

vi.mock('@/lib/actions/propicks-radar-dca.actions', () => ({ getRadarDcaOpportunities: vi.fn() }));
import { getRadarDcaOpportunities } from '@/lib/actions/propicks-radar-dca.actions';
import RadarDcaView from '@/components/proPicks/RadarDcaView';

const mockGet = vi.mocked(getRadarDcaOpportunities);

const RESULT: RadarDcaResult = {
    as_of: '2026-10-31',
    page: 1,
    page_size: 20,
    total: 2,
    has_more: false,
    sectors: ['Technology'],
    counts_by_level: { '4': 1, '1': 1 },
    coverage: { universe: 27, evaluated: 26, ok: 25, invalid: 1, stale: 0 },
    items: [
        {
            ticker: 'T04', name: 'Co 4', sector: 'Technology', currency: 'USD',
            level: 4, level_label: '4X DCA', status: 'forming', signal_date: '2026-10-29',
            close: 91.5, price_date: '2026-10-29', source: 'yfinance', price_verified: true,
            confirmed_level: 1, confirmed_period: '2026-09', clear_price_signal: true,
            change: { status: 'compared', changed: true, from_level: 3, to_level: 4, since_price_date: '2026-10-15' },
            formula_version: 'nico-v1', scan_date: '2026-10-30',
        },
        {
            ticker: 'T01', name: 'Co 1', sector: 'Technology', currency: 'USD',
            level: 1, level_label: '1X DCA', status: 'confirmed', signal_date: '2026-10-28',
            close: 50, price_date: '2026-10-28', source: 'yfinance', price_verified: false,
            confirmed_level: 1, confirmed_period: '2026-10', clear_price_signal: false,
            change: { status: 'history_pending', changed: null },
            formula_version: 'nico-v1', scan_date: '2026-10-30',
        },
    ],
};

describe('RadarDcaView', () => {
    beforeEach(() => {
        mockGet.mockReset();
        mockGet.mockResolvedValue(RESULT);
    });

    it('muestra nivel, estado, 4X claro y cobertura honesta', async () => {
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('T04')).toBeInTheDocument());
        expect(screen.getByText('4X claro')).toBeInTheDocument();
        expect(screen.getByText('En formación')).toBeInTheDocument();
        expect(screen.getByText('Confirmado')).toBeInTheDocument();
        expect(screen.getByText(/Cambio 3X → 4X/)).toBeInTheDocument();
        expect(screen.getByText('Precio sin verificación independiente')).toBeInTheDocument();
        expect(screen.getByText(/25 vigentes · 26 evaluadas de 27/)).toBeInTheDocument();
        // Sin etiquetas de fuente por tarjeta (petición de Nico); los datos
        // de fuente siguen en la API, solo se van de la vista.
        expect(screen.queryByText(/Fuente yfinance/)).not.toBeInTheDocument();
        expect(screen.queryByText(/barrido del 2026-10-30/)).not.toBeInTheDocument();
    });


    it('badge con etiqueta única: nada de "4X · 4X DCA" duplicado', async () => {
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('T04')).toBeInTheDocument());
        // Una sola ocurrencia del label, sin la doble escritura anterior.
        expect(screen.getAllByText('4X DCA')).toHaveLength(1);
        expect(screen.getAllByText('1X DCA')).toHaveLength(1);
        expect(screen.queryByText(/· \dX DCA/)).not.toBeInTheDocument();
    });

    it('recorte: etiqueta única RECORTE LIGERO sin el artefacto "-1X"', async () => {
        mockGet.mockResolvedValue({
            ...RESULT,
            total: 1,
            items: [
                {
                    ...RESULT.items[0],
                    ticker: 'TRIM',
                    level: -1,
                    level_label: 'RECORTE LIGERO',
                    clear_price_signal: false,
                },
            ],
        });
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('TRIM')).toBeInTheDocument());
        expect(screen.getByText('RECORTE LIGERO')).toBeInTheDocument();
        expect(screen.queryByText(/-1X/)).not.toBeInTheDocument();
    });

    it('sin level_label del backend: fallback "N X DCA" derivado del nivel', async () => {
        mockGet.mockResolvedValue({
            ...RESULT,
            total: 1,
            items: [{ ...RESULT.items[0], level: 2, level_label: null }],
        });
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('T04')).toBeInTheDocument());
        expect(screen.getByText('2X DCA')).toBeInTheDocument();
    });

    it('pide la página 2 con los mismos filtros al pulsar Siguiente', async () => {
        mockGet.mockResolvedValue({ ...RESULT, has_more: true, total: 40 });
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('T04')).toBeInTheDocument());
        fireEvent.click(screen.getByRole('button', { name: /Siguiente/ }));
        await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith(
            { page: 2, level: null, sector: null, outsideTracked: false },
        ));
    });

    it('vuelve a la página 1 al cambiar el filtro de nivel', async () => {
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('T04')).toBeInTheDocument());
        fireEvent.change(screen.getByRole('combobox', { name: 'Nivel' }), { target: { value: '4' } });
        await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith(
            { page: 1, level: 4, sector: null, outsideTracked: false },
        ));
    });

    it('error honesto sin oportunidades inventadas cuando la acción falla', async () => {
        mockGet.mockRejectedValue(new Error('down'));
        render(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText(/Radar DCA no disponible/)).toBeInTheDocument());
        expect(screen.queryByText('T04')).not.toBeInTheDocument();
    });
});
