// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

/**
 * Calendario de IPOs (/calendar/ipos): solo se pinta lo que la fuente publica
 * (precio fijado vs rango previsto), con huecos declarados («por confirmar»)
 * en vez de inventar, y aviso degradado cuando NASDAQ no responde.
 */
const getIpoCalendar = vi.fn();
vi.mock('@/lib/actions/catalysts.actions', () => ({
    getIpoCalendar: () => getIpoCalendar(),
}));
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: () => true }));
vi.mock('@/components/system/BackendOffline', () => ({ default: () => <p>backend caído</p> }));

import IposPage from '@/app/(root)/calendar/ipos/page';

const calendarOk = {
    status: 'ok',
    months: ['noviembre', 'diciembre'],
    count: 2,
    events: [
        {
            status: 'upcoming', symbol: 'NTRA', company: 'Nutra Labs', date: '2026-11-20',
            exchange: 'NASDAQ', price: '14-16 USD', offer_amount: '120 M USD',
        },
        {
            status: 'priced', symbol: 'BLQ', company: 'Bloque Inc', date: '2026-11-05',
            exchange: 'NYSE', price: '19 USD', offer_amount: '300 M USD',
        },
    ],
};

describe('página de IPOs', () => {
    it('separa próximas y fijadas, con rango previsto y precio fijado', async () => {
        getIpoCalendar.mockResolvedValue(calendarOk);
        render(await IposPage());
        expect(screen.getByText('Próximas salidas')).toBeInTheDocument();
        expect(screen.getByText('Precio fijado en el periodo')).toBeInTheDocument();
        expect(screen.getByText('Nutra Labs')).toBeInTheDocument();
        expect(screen.getByText(/rango 14-16 USD/)).toBeInTheDocument();
        expect(screen.getByText(/precio 19 USD/)).toBeInTheDocument();
        expect(screen.getByText(/oferta 300 M USD/)).toBeInTheDocument();
    });

    it('huecos de la fuente declarados, nunca inventados', async () => {
        getIpoCalendar.mockResolvedValue({
            ...calendarOk,
            events: [{ status: 'upcoming', symbol: null, company: null, date: null, exchange: null, price: null, offer_amount: null }],
        });
        render(await IposPage());
        expect(screen.getByText('ticker por confirmar')).toBeInTheDocument();
        expect(screen.getByText('Empresa sin nombre en la fuente')).toBeInTheDocument();
        expect(screen.getByText('fecha por confirmar')).toBeInTheDocument();
    });

    it('listas vacías: aviso de que la fuente no publica, no una página rota', async () => {
        getIpoCalendar.mockResolvedValue({ ...calendarOk, count: 0, events: [] });
        render(await IposPage());
        expect(screen.getByText(/no publica próximas salidas/)).toBeInTheDocument();
        expect(screen.getByText(/Ninguna salida fijó precio/)).toBeInTheDocument();
    });

    it('fuente degradada: aviso ámbar sin ocultar la incertidumbre', async () => {
        getIpoCalendar.mockResolvedValue({ ...calendarOk, status: 'partial' });
        render(await IposPage());
        expect(screen.getByText(/falló en alguno de los meses/)).toBeInTheDocument();
    });

    it('backend caído: pantalla de reintento, no un error en crudo', async () => {
        getIpoCalendar.mockRejectedValue(new Error('ECONNREFUSED'));
        render(await IposPage());
        expect(screen.getByText('backend caído')).toBeInTheDocument();
    });
});
