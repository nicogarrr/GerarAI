import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
const { redirect, getCatalystCalendar } = vi.hoisted(() => ({ redirect: vi.fn(), getCatalystCalendar: vi.fn() }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('next/navigation', () => ({ redirect }));
vi.mock('@/lib/actions/catalysts.actions', () => ({ getCatalystCalendar }));
vi.mock('@/components/alerts/AlertsManager', () => ({ default: () => <div>gestor-alertas</div> }));
import CalendarPage from '@/app/(root)/calendar/page';
import AlertsPage from '@/app/(root)/alerts/page';
beforeEach(() => { vi.clearAllMocks(); redirect.mockImplementation(() => { throw new Error('redirect'); }); });
it.each([
    [{ view: 'alertas' }, '/alerts'],
    [{ view: 'alertas', ticker: 'ASTS', tag: ['precio', 'noticias'], q: 'a & b' }, '/alerts?ticker=ASTS&tag=precio&tag=noticias&q=a+%26+b'],
])('redirige el enlace antiguo sin cargar el calendario ni perder parámetros', async (params, target) => {
    await expect(CalendarPage({ searchParams: Promise.resolve(params) })).rejects.toThrow('redirect');
    expect(redirect).toHaveBeenCalledWith(target);
    expect(getCatalystCalendar).not.toHaveBeenCalled();
});
it('el gestor canónico enlaza a resultados, no a catalizadores', async () => {
    render(await AlertsPage());
    expect(screen.getByText('gestor-alertas')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Resultados' })).toHaveAttribute('href', '/calendar/resultados');
});
