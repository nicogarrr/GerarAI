// Server component traducido con getT(): lib/i18n/server lee la cookie de
// locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

/**
 * CalendarEvents: agrupa por fecha, pinta el aviso ámbar cuando el calendario
 * viene degradado y convierte un backend caído en pantalla de reintento (sin
 * disfrazar otros errores). Los estados vacíos ya los cubre
 * calendar-page-empty.test.tsx.
 */
vi.mock('@/components/calendar/CompanyLogo', () => ({
    CompanyLogo: ({ ticker }: { ticker: string }) => <span data-testid="logo">{ticker}</span>,
}));
vi.mock('@/components/system/BackendOffline', () => ({ default: ({ feature }: { feature: string }) => <p>caído: {feature}</p> }));
const isBackendUnavailableError = vi.fn();
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: (e: unknown) => isBackendUnavailableError(e) }));

import { CalendarEvents } from '@/components/calendar/CalendarEvents';
import type { CatalystCalendar, CatalystEvent } from '@/lib/actions/catalysts.actions';

const event = (over: Partial<CatalystEvent>): CatalystEvent => ({
    date: '2026-11-10', ticker: 'AAPL', type: 'earnings', title: 'Resultados',
    detail: 'BPA estimado 1,50, tras el cierre', source: 'nasdaq', origin: 'cartera', ...over,
});
const calendar = (over: Partial<CatalystCalendar>): CatalystCalendar => ({
    status: 'ok', desde: '2026-11-09', hasta: '2026-11-23', held_count: 1,
    watchlist_count: 0, count: 1, events: [event({})], errors: [], ...over,
});
const show = async (cal: CatalystCalendar) => render(await CalendarEvents({ calendarPromise: Promise.resolve(cal) }));

describe('CalendarEvents', () => {
    it('agrupa por fecha: un encabezado por día y cada evento bajo su día', async () => {
        await show(calendar({
            count: 3,
            events: [
                event({ date: '2026-11-12', ticker: 'MSFT' }),
                event({ date: '2026-11-10', ticker: 'AAPL' }),
                event({ date: '2026-11-10', ticker: 'NVDA', type: 'dividend_ex', title: 'Ex-dividendo', detail: '0,83 por acción' }),
            ],
        }));
        const headings = await screen.findAllByRole('heading', { level: 2 });
        expect(headings).toHaveLength(2);
        // El orden de grupos es el de llegada de los eventos (12 antes que 10).
        expect(headings[0].textContent).toContain('12');
        expect(headings[1].textContent).toContain('10');
        expect(screen.getAllByTestId('logo')).toHaveLength(3);
        expect(screen.getAllByText('MSFT').length).toBeGreaterThan(0);
        expect(screen.getByText('0,83 por acción')).toBeInTheDocument();
    });

    it('etiqueta el tipo en español y marca el origen watchlist', async () => {
        await show(calendar({ events: [event({ type: 'dividend_ex', origin: 'watchlist' })], watchlist_count: 1 }));
        expect(await screen.findByText('Ex-dividendo')).toBeInTheDocument();
        expect(screen.getByText('Watchlist')).toBeInTheDocument();
    });

    it('una acción corporativa pinta su título, no la etiqueta genérica', async () => {
        await show(calendar({ events: [event({ type: 'corporate_action', title: 'Split', detail: 'ratio 4' })] }));
        expect(await screen.findByText('Split')).toBeInTheDocument();
        expect(screen.getByText('ratio 4')).toBeInTheDocument();
    });

    it('estado partial: aviso de lista posiblemente incompleta', async () => {
        await show(calendar({ status: 'partial' }));
        expect(await screen.findByRole('status')).toHaveTextContent('puede estar incompleta');
    });

    it('copia caducada: declara los días servidos desde la copia guardada', async () => {
        await show(calendar({ stale_days: ['2026-11-10'] }));
        const notices = await screen.findAllByRole('status');
        expect(notices.some((n) => /Copia guardada de .*10.* con más de una hora/.test(n.textContent ?? ''))).toBe(true);
    });

    it('sin copia caducada no pinta el aviso', async () => {
        await show(calendar({ stale_days: [] }));
        expect(screen.getAllByTestId('logo').length).toBeGreaterThan(0);
        expect(screen.queryByText(/Copia guardada/)).not.toBeInTheDocument();
    });

    it('estado unavailable: aviso de NASDAQ caído aunque no haya eventos', async () => {
        await show(calendar({ status: 'unavailable', events: [], count: 0 }));
        expect(await screen.findByRole('status')).toHaveTextContent('no responde');
        // Degradado no es «sin eventos en el rango»: no debe aparecer ese mensaje.
        expect(screen.queryByText(/Sin eventos en este rango/)).not.toBeInTheDocument();
    });

    it('backend caído: pantalla de reintento', async () => {
        isBackendUnavailableError.mockReturnValueOnce(true);
        render(await CalendarEvents({ calendarPromise: Promise.reject(new Error('connection refused')) }));
        expect(await screen.findByText(/caído: /)).toBeInTheDocument();
    });

    it('otro error del backend se propaga, no se disfraza', async () => {
        isBackendUnavailableError.mockReturnValueOnce(false);
        await expect(CalendarEvents({ calendarPromise: Promise.reject(new Error('boom 500')) })).rejects.toThrow('boom 500');
    });
});
