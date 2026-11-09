import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Cabecera a 768-1024px (md): con un nombre de usuario largo la caja del
// buscador se estrechaba tanto que el placeholder envolvía a dos líneas y el
// kbd «Ctrl+K» se montaba sobre el texto (medido en prod con la cuenta QA
// «Claude A - cuenta de prueba vacia, borrable»). El fix: el placeholder
// trunca en vez de envolver, el kbd no se encoge y el nombre del usuario
// trunca con max-w. Estas clases son las que impiden la rotura; si alguien
// las quita, el solape vuelve.

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: vi.fn().mockResolvedValue({ status: 'ok', stocks: [] }),
    getPopularStocks: vi.fn().mockResolvedValue([]),
}));
vi.mock('@/lib/actions/auth.actions', () => ({ signOut: vi.fn() }));
vi.mock('@/lib/auth/sign-out-flow', () => ({ runSignOut: vi.fn() }));
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

import SearchCommand from '@/components/SearchCommand';
import UserDropdown from '@/components/UserDropdown';

const LONG_NAME = 'Claude A - cuenta de prueba vacia, borrable con un nombre todavía más largo';

describe('Cabecera md: la caja del buscador no se rompe bajo presión de anchura', () => {
    it('el placeholder del gatillo trunca (min-w-0 + truncate) y no envuelve', () => {
        render(<SearchCommand renderAs="button" />);
        const trigger = screen.getByTestId('search-command-trigger');
        const label = trigger.querySelector('span');
        expect(label?.className).toContain('truncate');
        expect(label?.className).toContain('min-w-0');
        const kbd = trigger.querySelector('kbd');
        expect(kbd?.className).toContain('shrink-0');
    });

    it('el fallback pre-hidratado replica las mismas clases anti-rotura', async () => {
        const { readFileSync } = await import('node:fs');
        const source = readFileSync(`${process.cwd()}/components/SearchCommand.tsx`, 'utf8');
        // Botón hidratado y fallback SSR comparten estructura: los dos spans
        // de placeholder truncan y los dos kbd son shrink-0.
        const spans = source.match(/<span className="[^"]*">\{t\('ui\.search\.stocksPlaceholder'\)\}<\/span>/g) ?? [];
        expect(spans.length).toBe(2);
        for (const span of spans) {
            expect(span).toContain('truncate');
            expect(span).toContain('min-w-0');
        }
        const kbds = source.match(/<kbd className="[^"]*">/g) ?? [];
        expect(kbds.length).toBe(2);
        for (const kbd of kbds) {
            expect(kbd).toContain('shrink-0');
        }
    });
});

describe('Cabecera md: el nombre de usuario largo no se come el buscador', () => {
    it('el nombre visible trunca con max-w (el completo queda en el menú)', () => {
        render(<UserDropdown user={{ id: 'u1', name: LONG_NAME, email: 'qa@example.com' } as User} />);
        const visible = screen.getByText(LONG_NAME);
        expect(visible.className).toContain('truncate');
        expect(visible.className).toContain('max-w-36');
        expect(visible.className).toContain('lg:max-w-60');
        // not-sr-only resetea white-space y overflow: sin estos overrides el
        // nombre envuelve a varias líneas en vez de truncar con elipsis.
        expect(visible.className).toContain('md:whitespace-nowrap');
        expect(visible.className).toContain('md:overflow-hidden');
    });
});
