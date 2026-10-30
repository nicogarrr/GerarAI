import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

let pathname = '/calendar';
vi.mock('next/navigation', () => ({ usePathname: () => pathname }));

const getFollowedEarnings = vi.fn();
vi.mock('@/lib/actions/catalysts.actions', () => ({ getFollowedEarnings: (...a: unknown[]) => getFollowedEarnings(...a) }));
const createCalendarFeed = vi.fn();
const revokeCalendarFeed = vi.fn();
vi.mock('@/lib/actions/calendar-feed.actions', () => ({
    createCalendarFeed: (...a: unknown[]) => createCalendarFeed(...a),
    revokeCalendarFeed: (...a: unknown[]) => revokeCalendarFeed(...a),
}));
vi.mock('@/components/calendar/CompanyLogo', () => ({
    CompanyLogo: ({ ticker }: { ticker: string }) => <span data-testid="logo">{ticker}</span>,
}));

import { CalendarTabs } from '@/components/calendar/CalendarTabs';
import EarningsDayStrip from '@/components/calendar/EarningsDayStrip';
import SubscriptionManager, { SubscribeButtons } from '@/components/calendar/SubscriptionManager';
import {
    FollowedDaySources,
    FollowedEarningsRow,
    EventMaterialsLine,
    IrLine,
    MaterialsLine,
    dayHeading,
    fiscalLabel,
} from '@/components/calendar/FollowedEarningsList';
import type { FollowedEarningsEvent } from '@/lib/actions/catalysts.actions';

const ev = (over: Partial<FollowedEarningsEvent> = {}): FollowedEarningsEvent => ({
    ticker: 'KO', company: 'Coca-Cola', origin: 'cartera', date: '2026-10-28', session: 'pre_market',
    fiscal_label: 'Sep/2026', confirmed: true, source: 'Nasdaq', source_url: 'https://example.com/ko', ...over,
});

beforeEach(() => {
    pathname = '/calendar';
    getFollowedEarnings.mockReset();
    createCalendarFeed.mockReset();
    revokeCalendarFeed.mockReset();
});

describe('CalendarTabs', () => {
    it('incluye la pestaña de IPOs y la activa solo en /calendar/ipos', () => {
        pathname = '/calendar/ipos';
        render(<CalendarTabs />);
        expect(screen.getByRole('link', { name: 'IPOs' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'Catalizadores' })).not.toHaveAttribute('aria-current');
    });

    it('marca solo la pestaña de href más largo: /calendar/resultados no enciende /calendar', () => {
        pathname = '/calendar/resultados';
        render(<CalendarTabs />);
        expect(screen.getByRole('link', { name: 'Resultados' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'Catalizadores' })).not.toHaveAttribute('aria-current');
    });
    it('una subruta enciende su pestaña y /calendar solo la de catalizadores', () => {
        pathname = '/calendar/suscripcion/x';
        const { unmount } = render(<CalendarTabs />);
        expect(screen.getByRole('link', { name: 'Suscribir' })).toHaveAttribute('aria-current', 'page');
        unmount();
        pathname = '/calendar';
        render(<CalendarTabs />);
        expect(screen.getByRole('link', { name: 'Catalizadores' })).toHaveAttribute('aria-current', 'page');
    });
    it('«Cartera» es la primera pestaña y enlaza a /portfolio', () => {
        pathname = '/calendar';
        render(<CalendarTabs />);
        const links = screen.getAllByRole('link');
        expect(links[0]).toHaveTextContent('Cartera');
        expect(links[0]).toHaveAttribute('href', '/portfolio');
        expect(links[0]).not.toHaveAttribute('aria-current');
    });
    it('fuera de las pestañas no hay ninguna activa', () => {
        pathname = '/otra';
        render(<CalendarTabs />);
        expect(document.querySelector('[aria-current="page"]')).toBeNull();
    });
    it('muestra un degradado a la derecha solo si hay pestañas fuera de pantalla', () => {
        pathname = '/calendar';
        const widths = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(500);
        const client = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(390);
        const { unmount } = render(<CalendarTabs />);
        expect(screen.getByTestId('calendar-tabs-fade-right')).toBeInTheDocument();
        expect(screen.queryByTestId('calendar-tabs-fade-left')).toBeNull();
        unmount();
        widths.mockReturnValue(390);
        render(<CalendarTabs />);
        expect(screen.queryByTestId('calendar-tabs-fade-right')).toBeNull();
        widths.mockRestore();
        client.mockRestore();
    });
    it('desplaza la barra solo si la pestaña activa no cabe', () => {
        pathname = '/macro-calendar';
        const spy = vi.spyOn(HTMLElement.prototype, 'offsetLeft', 'get').mockReturnValue(500);
        vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
        vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(200);
        render(<CalendarTabs />);
        expect(spy).toHaveBeenCalled();
        // left=0 (500-500), right=100 <= 0+200: cabe, no se mueve
        expect(screen.getByRole('navigation', { name: 'Calendarios' }).scrollLeft).toBe(0);
    });
    it('desplaza hacia la derecha si la activa queda fuera por la derecha', () => {
        pathname = '/corporate-actions';
        let call = 0;
        vi.spyOn(HTMLElement.prototype, 'offsetLeft', 'get').mockImplementation(() => (call++ % 2 === 0 ? 900 : 0));
        vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
        vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(200);
        render(<CalendarTabs />);
        expect(screen.getByRole('navigation', { name: 'Calendarios' }).scrollLeft).toBe(900 + 100 - 200 + 8);
    });
    it('desplaza hacia la izquierda si la activa queda a la izquierda', () => {
        pathname = '/calendar/resultados';
        let call = 0;
        vi.spyOn(HTMLElement.prototype, 'offsetLeft', 'get').mockImplementation(() => (call++ % 2 === 0 ? 0 : 0));
        const nav = () => screen.getByRole('navigation', { name: 'Calendarios' });
        const { unmount } = render(<CalendarTabs />);
        unmount();
        // fuerza scrollLeft previo mayor que la posición de la activa
        vi.spyOn(HTMLElement.prototype, 'scrollLeft', 'get').mockReturnValue(300);
        const sets: number[] = [];
        vi.spyOn(HTMLElement.prototype, 'scrollLeft', 'set').mockImplementation((v) => { sets.push(v); });
        render(<CalendarTabs />);
        expect(nav()).toBeInTheDocument();
        expect(sets).toEqual([0]);
    });
});

describe('EarningsDayStrip', () => {
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(new Date());
    const plus = (n: number) => {
        const d = new Date(`${today}T00:00:00Z`);
        d.setUTCDate(d.getUTCDate() + n);
        return d.toISOString().slice(0, 10);
    };
    it('si el backend falla, no pinta nada (no rompe la home)', async () => {
        getFollowedEarnings.mockRejectedValue(new Error('down'));
        expect(await EarningsDayStrip()).toBeNull();
    });
    it('sin empresas seguidas se omite', async () => {
        getFollowedEarnings.mockResolvedValue({ followed_count: 0, days: [] });
        expect(await EarningsDayStrip()).toBeNull();
    });
    it('pinta 7 días con Hoy/Mañana, cuenta eventos y resume los logos sobrantes', async () => {
        getFollowedEarnings.mockResolvedValue({
            followed_count: 3,
            days: [
                { date: today, events: [ev({ ticker: 'A' }), ev({ ticker: 'B' }), ev({ ticker: 'C' }), ev({ ticker: 'D' })] },
                { date: plus(1), events: [ev({ ticker: 'E', company: '' })] },
            ],
        });
        render(await EarningsDayStrip());
        expect(screen.getAllByRole('link', { name: /^Resultados del/ })).toHaveLength(7);
        expect(screen.getByText('Hoy')).toBeInTheDocument();
        expect(screen.getByText('Mañana')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /4 eventos$/ })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /1 evento$/ })).toBeInTheDocument();
        expect(screen.getByText('+2')).toBeInTheDocument();
        expect(screen.getAllByText('Sin eventos')).toHaveLength(5);
        expect(screen.getByRole('link', { name: 'Ver todo' })).toHaveAttribute('href', '/calendar/resultados');
    });
    it('cada tarjeta enlaza a su día en /calendar/resultados para ver todas las empresas', async () => {
        getFollowedEarnings.mockResolvedValue({
            followed_count: 3,
            days: [{ date: plus(2), events: [ev({ ticker: 'A' }), ev({ ticker: 'B' }), ev({ ticker: 'C' })] }],
        });
        render(await EarningsDayStrip());
        const card = screen.getByRole('link', { name: /3 eventos$/ });
        expect(card).toHaveAttribute('href', `/calendar/resultados#d-${plus(2)}`);
        // El ancla existe en la página de resultados: <h2 id={`d-${day.date}`}>.
        // Días sin eventos conservan el enlace (sin ancla destino, no pasa nada).
        expect(screen.getAllByRole('link', { name: /Sin eventos$/ })[0]).toHaveAttribute('href', expect.stringMatching(/^\/calendar\/resultados#d-\d{4}-\d{2}-\d{2}$/));
    });
    it('el «+N» es visible de verdad y los logos no se encogen cuando sobran eventos', async () => {
        getFollowedEarnings.mockResolvedValue({
            followed_count: 3,
            days: [{ date: today, events: [ev({ ticker: 'A' }), ev({ ticker: 'B' }), ev({ ticker: 'C' })] }],
        });
        render(await EarningsDayStrip());
        // 3 eventos: 2 logos a tamaño completo (size-9) y «+1» con jerarquía
        // (text-sm semibold, no el gris tenue de antes que pasaba desapercibido).
        const more = screen.getByText('+1');
        expect(more.className).toMatch(/\btext-sm\b/);
        expect(more.className).toMatch(/\bfont-semibold\b/);
        const logos = screen.getAllByTestId('logo');
        expect(logos).toHaveLength(2);
    });
    it('la tira ancla el scroll a tarjetas enteras (sin descansos a media tarjeta)', async () => {
        // Captura de prod 30-oct-2026 (390 px): la primera tarjeta aparecía
        // cortada por el borde izquierdo cuando la tira quedaba a medio
        // desplazar. snap-mandatory + scroll-pl-4 fuerzan el reposo sobre una
        // tarjeta entera, respetando el sangrado px-4 del borde.
        getFollowedEarnings.mockResolvedValue({ followed_count: 1, days: [{ date: today, events: [ev()] }] });
        render(await EarningsDayStrip());
        const card = screen.getAllByRole('link', { name: /^Resultados del/ })[0];
        const scroller = card.parentElement as HTMLElement;
        expect(scroller.className).toMatch(/\bsnap-x\b/);
        expect(scroller.className).toMatch(/\bsnap-mandatory\b/);
        expect(scroller.className).toMatch(/\bscroll-pl-4\b/);
        expect(card.className).toMatch(/\bsnap-start\b/);
    });
    it('la tira horizontal contiene sus etiquetas sr-only (sin desborde de la página en móvil)', async () => {
        // Suite E2E de flujos (28-oct-2026), /inicio a 375 px: las etiquetas
        // sr-only (position:absolute) de las tarjetas no tenían un ancestro
        // posicionado dentro del carrusel, se escapaban de su overflow-x-auto
        // y ensanchaban el viewport de layout a 819 px (página desplazable en
        // horizontal). El carrusel tiene que ser su bloque contenedor.
        getFollowedEarnings.mockResolvedValue({ followed_count: 1, days: [{ date: today, events: [ev()] }] });
        render(await EarningsDayStrip());
        const card = screen.getAllByRole('link', { name: /^Resultados del/ })[0];
        const scroller = card.parentElement as HTMLElement;
        expect(scroller.className).toMatch(/\boverflow-x-auto\b/);
        expect(scroller.className).toMatch(/(^|\s)relative(\s|$)/);
        expect(card.querySelectorAll('.sr-only').length).toBeGreaterThan(0);
    });
});

describe('FollowedEarningsList helpers', () => {
    it('fiscalLabel: formato Mmm/AAAA se reescribe, el desconocido se muestra tal cual, null es null', () => {
        expect(fiscalLabel('Sep/2026')).toBe('Cierre Sep 2026');
        expect(fiscalLabel('Q3 FY26')).toBe('Q3 FY26');
        expect(fiscalLabel(null)).toBeNull();
        expect(fiscalLabel('')).toBeNull();
    });
    it('dayHeading distingue hoy, mañana y otro día', () => {
        expect(dayHeading('2026-10-20', '2026-10-20')).toMatch(/^Hoy, /);
        expect(dayHeading('2026-10-21', '2026-10-20')).toMatch(/^Mañana, /);
        const other = dayHeading('2026-10-23', '2026-10-20');
        expect(other).not.toMatch(/^Hoy|^Mañana/);
        expect(other).toMatch(/23/);
    });
});

describe('MaterialsLine', () => {
    const base = { filed_at: '2026-10-20', filing_url: null, documents: [] };
    it('sin dato o sin cobertura no pinta nada', () => {
        expect(render(<MaterialsLine materials={undefined} />).container).toBeEmptyDOMElement();
        expect(render(<MaterialsLine materials={{ ...base, status: 'sin_cobertura_sec' }} />).container).toBeEmptyDOMElement();
        expect(render(<MaterialsLine materials={{ ...base, status: 'periodo_no_coincide' }} />).container).toBeEmptyDOMElement();
    });
    it('no_disponible y sin_filing dicen lo que pasa', () => {
        render(<MaterialsLine materials={{ ...base, status: 'no_disponible' }} />);
        expect(screen.getByText('Enlace no disponible')).toBeInTheDocument();
        render(<MaterialsLine materials={{ ...base, status: 'sin_filing' }} />);
        expect(screen.getByText(/Sin 8-K de resultados/)).toBeInTheDocument();
    });
    it('ok sin documentos se trata como sin 8-K', () => {
        render(<MaterialsLine materials={{ ...base, status: 'ok' }} />);
        expect(screen.getByText(/Sin 8-K de resultados/)).toBeInTheDocument();
    });
    it('ok con documentos enlaza cada uno en pestaña nueva y muestra la fecha de la SEC', () => {
        render(<MaterialsLine materials={{ ...base, status: 'ok', documents: [{ url: 'https://sec.gov/a', label: 'Nota de prensa', exhibit: 'EX-99.1' }] as never }} />);
        const link = screen.getByRole('link', { name: /Nota de prensa/ });
        expect(link).toHaveAttribute('href', 'https://sec.gov/a');
        expect(link).toHaveAttribute('target', '_blank');
        expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
        expect(screen.getByText('SEC · 20 oct 2026')).toBeInTheDocument();
    });
    it('EventMaterialsLine toma solo la fila de su clave', async () => {
        const promise = Promise.resolve({ 'KO#1': { ...base, status: 'no_disponible' as const } });
        render(await EventMaterialsLine({ promise, eventKey: 'KO#1' }));
        expect(screen.getByText('Enlace no disponible')).toBeInTheDocument();
        const none = await EventMaterialsLine({ promise, eventKey: 'otra' });
        expect(render(none).container).toBeEmptyDOMElement();
    });
});

describe('IrLine', () => {
    it('ticker fuera del registro: nada', () => {
        expect(render(<IrLine ticker="ZZZZ" date="2026-10-28" />).container).toBeEmptyDOMElement();
    });
    it('fecha con página de evento: enlace al evento y sus archivos oficiales', () => {
        render(<IrLine ticker="meta" date="2026-10-21" />);
        expect(screen.getByRole('link', { name: /Evento T3 2026 en IR/ })).toHaveAttribute('href', expect.stringContaining('Q3-2026-Earnings-Call'));
        expect(screen.getByRole('link', { name: /Webcast/ })).toHaveAttribute('target', '_blank');
        expect(screen.getByRole('link', { name: /Presentación/ })).toBeInTheDocument();
    });
    it('fecha sin página: solo la sección general, y el aviso lo dice', () => {
        render(<IrLine ticker="TSLA" date="2026-10-22" />);
        const link = screen.getByRole('link', { name: /Documentos y eventos \(IR\)/ });
        expect(link).toHaveAttribute('href', 'https://ir.tesla.com/');
        expect(link.getAttribute('title')).toContain('no la página de este evento');
        expect(screen.queryByRole('link', { name: /Evento/ })).not.toBeInTheDocument();
    });
});

describe('FollowedEarningsRow / FollowedDaySources', () => {
    it('muestra sesión, cierre, fuente y enlace a la ficha con el ticker codificado', () => {
        render(<ul><FollowedEarningsRow event={ev({ ticker: 'BRK.B' })} /></ul>);
        expect(screen.getByText('Antes de apertura')).toBeInTheDocument();
        expect(screen.getByText('Cierre Sep 2026')).toBeInTheDocument();
        expect(screen.queryByText('Estimada')).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Fuente de la fecha de BRK.B: Nasdaq' })).toHaveAttribute('href', 'https://example.com/ko');
        expect(screen.getByRole('link', { name: 'Abrir Coca-Cola' })).toHaveAttribute('href', '/research/BRK.B');
    });
    it('sin sesión: hora por confirmar; estimada marcada; sin fuente no hay enlace de fuente; sin empresa usa el ticker', () => {
        render(<ul><FollowedEarningsRow event={ev({ session: null, confirmed: false, source_url: null, fiscal_label: null, company: '' })} materialsSlot={<span>slot</span>} /></ul>);
        expect(screen.getByText('Hora por confirmar')).toBeInTheDocument();
        expect(screen.getByText('Estimada')).toBeInTheDocument();
        expect(screen.queryByRole('link', { name: /Fuente de la fecha/ })).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Abrir KO' })).toBeInTheDocument();
        expect(screen.getByText('slot')).toBeInTheDocument();
    });
    it('tras el cierre', () => {
        render(<ul><FollowedEarningsRow event={ev({ session: 'after_market', confirmed: null })} /></ul>);
        expect(screen.getByText('Tras el cierre')).toBeInTheDocument();
        expect(screen.queryByText('Estimada')).not.toBeInTheDocument();
    });
    it('FollowedDaySources: sin eventos nada; deduplica fuentes y pluraliza', () => {
        expect(render(<FollowedDaySources events={[]} />).container).toBeEmptyDOMElement();
        const { container } = render(<FollowedDaySources events={[ev(), ev({ ticker: 'X' }), ev({ source: 'Zacks', source_url: null })]} />);
        expect(container.textContent).toBe('Fuentes: Nasdaq · Zacks');
        expect(screen.getAllByRole('link')).toHaveLength(1);
    });
    it('FollowedDaySources: una sola fuente va en singular', () => {
        const { container } = render(<FollowedDaySources events={[ev()]} />);
        expect(container.textContent).toBe('Fuente: Nasdaq');
    });
});

describe('SubscribeButtons', () => {
    it('apple usa webcal://, google y outlook codifican el enlace y abren pestaña nueva', () => {
        render(<SubscribeButtons origin="https://gerarai.vercel.app" token="tok" />);
        const cta = () => screen.getByRole('link', { name: /Suscribirse con/ });
        expect(cta()).toHaveAttribute('href', 'webcal://gerarai.vercel.app/api/calendar-feed/tok.ics');
        expect(cta()).not.toHaveAttribute('target');
        expect(screen.getByLabelText('Enlace de suscripción')).toHaveValue('https://gerarai.vercel.app/api/calendar-feed/tok.ics');
        fireEvent.click(screen.getByRole('tab', { name: 'google' }));
        expect(cta().getAttribute('href')).toBe(`https://calendar.google.com/calendar/r?cid=${encodeURIComponent('webcal://gerarai.vercel.app/api/calendar-feed/tok.ics')}`);
        expect(cta()).toHaveAttribute('target', '_blank');
        fireEvent.click(screen.getByRole('tab', { name: 'outlook' }));
        expect(cta().getAttribute('href')).toContain('outlook.live.com/calendar/0/addfromweb?url=' + encodeURIComponent('https://gerarai.vercel.app/api/calendar-feed/tok.ics'));
        expect(screen.getByRole('tab', { name: 'outlook' })).toHaveAttribute('aria-selected', 'true');
        expect(screen.getByText('Confirma «Suscribirse» en Outlook.')).toBeInTheDocument();
    });
    it('copiar escribe el https en el portapapeles y muestra Copiado un momento', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        render(<SubscribeButtons origin="http://localhost:3000" token="t" />);
        const input = screen.getByLabelText('Enlace de suscripción');
        fireEvent.focus(input);
        fireEvent.click(screen.getByRole('button', { name: 'Copiar' }));
        await screen.findByRole('button', { name: 'Copiado' });
        expect(writeText).toHaveBeenCalledWith('http://localhost:3000/api/calendar-feed/t.ics');
        act(() => { vi.advanceTimersByTime(2100); });
        expect(screen.getByRole('button', { name: 'Copiar' })).toBeInTheDocument();
        vi.useRealTimers();
    });
});

describe('SubscriptionManager', () => {
    const inactive = { active: false, scope: null, created_at: null, last_used_at: null } as const;
    const active = { active: true, scope: 'followed', created_at: '2026-10-20T10:00:00Z', last_used_at: null } as const;
    it('por defecto el filtro es watchlist (menos expuesto) y se puede cambiar antes de crear', async () => {
        createCalendarFeed.mockResolvedValue({ token: 'abc' });
        render(<SubscriptionManager initialState={inactive} origin="https://x.test" />);
        expect(screen.getByRole('button', { name: 'Solo la watchlist' })).toHaveAttribute('aria-pressed', 'true');
        expect(screen.getByText(/tu cartera no se comparte/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Cartera y watchlist' }));
        expect(screen.getByText(/posiciones de tu cartera y de tu watchlist/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Crear suscripción' }));
        await screen.findByRole('region', { name: 'Configuración' });
        expect(createCalendarFeed).toHaveBeenCalledWith('followed');
        expect(screen.getByLabelText('Enlace de suscripción')).toHaveValue('https://x.test/api/calendar-feed/abc.ics');
        expect(screen.getByRole('region', { name: 'Suscripción activa' })).toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Filtro' })).not.toBeInTheDocument();
    });
    it('si crear falla muestra el error y no activa nada', async () => {
        createCalendarFeed.mockRejectedValue(new Error('x'));
        render(<SubscriptionManager initialState={inactive} origin="https://x.test" />);
        fireEvent.click(screen.getByRole('button', { name: 'Crear suscripción' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo crear la suscripción');
        expect(screen.getByRole('button', { name: 'Crear suscripción' })).toBeInTheDocument();
    });
    it('activa: regenerar conserva el filtro y revocar vuelve al estado inicial', async () => {
        createCalendarFeed.mockResolvedValue({ token: 'new' });
        revokeCalendarFeed.mockResolvedValue(undefined);
        render(<SubscriptionManager initialState={active} origin="https://x.test" />);
        expect(screen.getByText('Cartera y watchlist')).toBeInTheDocument();
        expect(screen.getByText(/creada el/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Regenerar enlace' }));
        await screen.findByLabelText('Enlace de suscripción');
        expect(createCalendarFeed).toHaveBeenCalledWith('followed');
        // El enlace aparece antes de que termine useTransition; espera el
        // botón operativo antes de simular el siguiente gesto del usuario.
        await waitFor(() => expect(screen.getByRole('button', { name: 'Desactivar' })).toBeEnabled());
        fireEvent.click(screen.getByRole('button', { name: 'Desactivar' }));
        await screen.findByRole('button', { name: 'Crear suscripción' });
        expect(revokeCalendarFeed).toHaveBeenCalledTimes(1);
        expect(screen.queryByLabelText('Enlace de suscripción')).not.toBeInTheDocument();
    }, 10_000);

    it('si desactivar falla, sigue activa y avisa', async () => {
        revokeCalendarFeed.mockRejectedValue(new Error('x'));
        render(<SubscriptionManager initialState={active} origin="https://x.test" />);
        fireEvent.click(screen.getByRole('button', { name: 'Desactivar' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo desactivar');
        expect(screen.getByRole('region', { name: 'Suscripción activa' })).toBeInTheDocument();
    });
});
void waitFor;
