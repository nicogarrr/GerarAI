import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

/**
 * Menú de usuario en móvil (390px): un nombre o email largo no puede empujar
 * el menú fuera de la pantalla (hallazgo QA 2026-11-08: el panel se salía por
 * el borde derecho y el nombre se cortaba en el borde). El panel se acota al
 * viewport y los textos se truncan con ellipsis.
 */
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/auth.actions', () => ({ signOut: vi.fn() }));

import UserDropdown from '@/components/UserDropdown';
import { createTranslator } from '@/lib/i18n/translate';

const LONG_NAME = 'Claude A - cuenta de prueba vacia, borrable, con un nombre larguisimo';
const LONG_EMAIL = 'claude.empty.20261030.muy.largo@example.invalid';

describe('UserDropdown', () => {
    it('acota el panel al viewport y trunca nombre y email largos', async () => {
        render(<UserDropdown user={{ id: 'u1', name: LONG_NAME, email: LONG_EMAIL } as never} />);
        fireEvent.keyDown(screen.getByRole('button'), { key: 'Enter' });
        const menu = await screen.findByRole('menu');
        expect(menu.className).toContain('max-w-[calc(100vw-1rem)]');
        expect(within(menu).getByText(LONG_NAME).className).toContain('truncate');
        expect(within(menu).getByText(LONG_EMAIL).className).toContain('truncate');
    });

    it('el nombre accesible es exacto en es y en: sin espacio antes de la coma', () => {
        // El nombre accesible sale de shell.user.menuLabel interpolada en UN
        // span sr-only; con spans hermanos Chromium metia un espacio y quedaba
        // "…borrable , menú de usuario". Assert exacto (auditor #4924).
        expect(createTranslator('es')('shell.user.menuLabel', { name: 'Claude' })).toBe('Claude, menú de usuario');
        expect(createTranslator('en')('shell.user.menuLabel', { name: 'Claude' })).toBe('Claude, user menu');
    });

    it('el gatillo renderiza el nombre accesible exacto en es', () => {
        render(<UserDropdown user={{ id: 'u1', name: 'Browser Analyst', email: 'a@b.es' } as never} />);
        expect(screen.getByRole('button')).toHaveAccessibleName('Browser Analyst, menú de usuario');
    });
});
