import axe from 'axe-core';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// axe-core (4.14, el mismo motor que el barrido e2e/a11y-routes-axe) sobre los
// componentes que el barrido de pantallas firmadas marco como serios. Solo
// reglas que no dependen de layout real (jsdom no pinta): nombre accesible vs
// texto visible (WCAG 2.5.3) y estructura de listas de definicion (1.3.1).
// El contraste y el subrayado de enlaces se comprueban en el e2e.

vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/auth.actions', () => ({ signOut: vi.fn() }));
const getFollowedEarnings = vi.fn();
vi.mock('@/lib/actions/catalysts.actions', () => ({ getFollowedEarnings: (...a: unknown[]) => getFollowedEarnings(...a) }));
vi.mock('@/components/calendar/CompanyLogo', () => ({
    CompanyLogo: ({ ticker }: { ticker: string }) => <span data-testid="logo">{ticker}</span>,
}));
const getExtendedQuotes = vi.fn();
vi.mock('@/lib/actions/watchlist.actions', () => ({ getExtendedQuotes: (...a: unknown[]) => getExtendedQuotes(...a) }));

import UserDropdown from '@/components/UserDropdown';
import EarningsDayStrip from '@/components/calendar/EarningsDayStrip';
import ExtendedHoursLine from '@/components/common/ExtendedHoursLine';

async function axeViolations(node: Element, rules: string[]) {
    const result = await axe.run(node, { runOnly: { type: 'rule', values: rules } });
    return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' | ')}`);
}

beforeEach(() => {
    getFollowedEarnings.mockReset();
    getExtendedQuotes.mockReset();
});

describe('a11y: nombre accesible contiene el texto visible (label-in-name)', () => {
    it('el gatillo del menu de usuario se nombra por el nombre visible, sin aria-label que lo contradiga', async () => {
        const { container } = render(<UserDropdown user={{ id: 'u1', name: 'Browser Analyst', email: 'a@b.es' } as User} />);
        expect(await axeViolations(container, ['label-content-name-mismatch', 'button-name'])).toEqual([]);
        const trigger = screen.getByRole('button', { name: /Browser Analyst/ });
        expect(trigger).not.toHaveAttribute('aria-label');
        // Sigue diciendo que es el menu de usuario (lo usan los e2e de navegacion).
        expect(trigger).toHaveAccessibleName(/men[uú] de usuario/i);
    });

    it('cada dia de la tira de resultados se nombra con lo que se ve (fecha, dia y eventos)', async () => {
        const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(new Date());
        getFollowedEarnings.mockResolvedValue({
            followed_count: 1,
            days: [{ date: today, events: [{ ticker: 'KO', company: 'Coca-Cola', origin: 'cartera', date: today, session: 'pre_market', fiscal_label: null, confirmed: true, source: 'Nasdaq', source_url: null }] }],
        });
        const { container } = render((await EarningsDayStrip())!);
        expect(await axeViolations(container, ['label-content-name-mismatch', 'link-name'])).toEqual([]);
        const links = screen.getAllByRole('link', { name: /^Resultados del/ });
        expect(links).toHaveLength(7);
        for (const link of links) expect(link).not.toHaveAttribute('aria-label');
    });
});

describe('a11y: <dl> solo agrupa dt/dd (definition-list)', () => {
    it('la linea de pre/post-mercado dentro de una ficha <dl> es un <dd>', async () => {
        getExtendedQuotes.mockImplementation(async (symbols: string[]) =>
            Object.fromEntries(symbols.map((s) => [s, {
                symbol: s, price: 101.5, currency: 'USD', change_percent: 0.4, price_session: 'post', session: 'post',
                source: 'yahoo', status: 'ok', timestamp: 1_790_000_000, regular_close_timestamp: 1_789_990_000,
            }])),
        );
        const { container } = render(
            <dl>
                <div>
                    <dt>Precio</dt>
                    <dd>100 USD</dd>
                    <ExtendedHoursLine symbol="AAPL" currency="USD" as="dd" />
                </div>
            </dl>,
        );
        await waitFor(() => expect(screen.getByText(/Post-cierre/)).toBeInTheDocument());
        expect(screen.getByText(/Post-cierre/).tagName).toBe('DD');
        expect(await axeViolations(container, ['definition-list', 'dlitem'])).toEqual([]);
    });
});
