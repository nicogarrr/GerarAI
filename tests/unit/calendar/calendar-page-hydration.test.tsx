// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/catalysts.actions', () => ({ getCatalystCalendar: () => new Promise(() => {}) }));
vi.mock('next/navigation', () => ({ redirect: vi.fn(), usePathname: () => '/calendar' }));
import CalendarPage from '@/app/(root)/calendar/page';

/**
 * /calendar lanzaba React #418 (hidratación) en cada carga: el skeleton de la
 * descripción era un <div> dentro del <p> de PageHeader. El parser HTML del
 * navegador cierra el <p> al ver el <div>, así que el DOM del SSR no casaba
 * con el árbol de React. Se comprueba con el HTML real del servidor parseado
 * como lo parsea el navegador.
 */
describe('/calendar: HTML del servidor válido para hidratar', () => {
    it('el skeleton de la descripción queda dentro del <p> al parsear el HTML', async () => {
        const html = renderToString(await CalendarPage({ searchParams: Promise.resolve({}) }));
        const host = document.createElement('div');
        host.innerHTML = html;
        const description = host.querySelector('header p.mt-2');
        expect(description).not.toBeNull();
        // Si el fallback fuese un bloque (<div>), el parser lo sacaría del <p>.
        expect(description!.querySelector('.animate-pulse')).not.toBeNull();
        expect(host.querySelectorAll('header p.mt-2')).toHaveLength(1);
        expect(html).not.toMatch(/<p class="mt-2[^"]*">(?:(?!<\/p>)[\s\S])*<div/);
    });
});
