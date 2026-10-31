// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

/**
 * Usuario nuevo (sin posiciones ni watchlist): el calendario de catalizadores
 * no puede quedarse en un «no hay nada que seguir» sin salida; ofrece los dos
 * primeros pasos que lo llenan.
 */
const getCatalystCalendar = vi.fn();
vi.mock('@/lib/actions/catalysts.actions', () => ({
    getCatalystCalendar: () => getCatalystCalendar(),
}));
vi.mock('next/navigation', () => ({ redirect: vi.fn() }));

// La página pinta la cabecera al instante y los eventos llegan por
// streaming (Suspense): estos estados se prueban sobre CalendarEvents, el
// server component async que los renderiza.
import CalendarPage, { CalendarEvents } from '@/app/(root)/calendar/page';

describe('calendario de catalizadores: estado vacío de un usuario nuevo', () => {
    it('sin posiciones ni watchlist enlaza a añadir empresa y a añadir inversión', async () => {
        getCatalystCalendar.mockResolvedValue({
            status: 'ok', desde: '2026-10-30', hasta: '2026-11-13', count: 0, events: [],
            held_count: 0, watchlist_count: 0,
        });
        render(await CalendarEvents({ calendarPromise: Promise.resolve(getCatalystCalendar()) }));
        expect(screen.getByText(/No tienes posiciones abiertas ni watchlist/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Añadir a la watchlist' })).toHaveAttribute('href', '/watchlist?anadir=1');
        expect(screen.getByRole('link', { name: 'Añadir inversión' })).toHaveAttribute('href', '/portfolio?anadir=1');
    });

    it('con posiciones pero sin eventos no muestra los enlaces de primer uso', async () => {
        getCatalystCalendar.mockResolvedValue({
            status: 'ok', desde: '2026-10-30', hasta: '2026-11-13', count: 0, events: [],
            held_count: 2, watchlist_count: 0,
        });
        render(await CalendarEvents({ calendarPromise: Promise.resolve(getCatalystCalendar()) }));
        expect(screen.getByText(/Sin eventos en este rango/)).toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'Añadir inversión' })).not.toBeInTheDocument();
    });

    it('la cabecera pinta sin esperar al calendario (streaming)', async () => {
        getCatalystCalendar.mockReturnValue(new Promise(() => {})); // nunca resuelve
        render(await CalendarPage({ searchParams: Promise.resolve({}) }));
        expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Alertas' })).toHaveAttribute('href', '/alerts');
    });
});
