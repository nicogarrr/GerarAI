import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/auth.actions', () => ({}));
vi.mock('@/lib/actions/privacy.actions', () => ({}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }), useSearchParams: () => new URLSearchParams() }));

import TwoFactorSettings from '@/components/security/TwoFactorSettings';
import PrivacySettings from '@/components/security/PrivacySettings';
import { LocaleProvider } from '@/lib/i18n/client';
import es from '@/lib/i18n/messages/es/security.json';
import en from '@/lib/i18n/messages/en/security.json';

describe('Seguridad en inglés', () => {
    it('mismas claves en los dos idiomas', () => {
        for (const area of ['twoFactor', 'privacy', 'page'] as const) {
            expect(Object.keys(en[area]).sort()).toEqual(Object.keys(es[area]).sort());
        }
    });

    it('2FA y privacidad en inglés', () => {
        render(<LocaleProvider locale="en"><TwoFactorSettings initiallyEnabled={false} /><PrivacySettings email="a@b.c" /></LocaleProvider>);
        expect(screen.getByText('Two-step verification (2FA)')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Turn on 2FA' })).toBeTruthy();
        expect(screen.getByText('Export my data')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Delete account and all my data' })).toBeTruthy();
    });

    it('en español no cambia', () => {
        render(<LocaleProvider locale="es"><TwoFactorSettings initiallyEnabled /></LocaleProvider>);
        expect(screen.getByText('✓ La verificación en dos pasos está activada')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Desactivar 2FA' })).toBeTruthy();
    });
});
