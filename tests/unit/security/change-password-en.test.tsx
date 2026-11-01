import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { callAuthEndpoint, requireAuthenticatedUser, getLocale } = vi.hoisted(() => ({
    callAuthEndpoint: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    getLocale: vi.fn(),
}));
vi.mock('@/lib/auth/endpoint', () => ({ callAuthEndpoint }));
vi.mock('@/lib/auth/email', () => ({ isPasswordResetEmailConfigured: () => false }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/i18n/server', () => ({ getLocale }));

import ChangePassword from '@/components/security/ChangePassword';
import { changePassword, requestPasswordReset, resetPasswordWithToken } from '@/lib/actions/password.actions';
import { LocaleProvider } from '@/lib/i18n/client';
import es from '@/lib/i18n/messages/es/security.json';
import en from '@/lib/i18n/messages/en/security.json';

describe('Contraseña en inglés', () => {
    it('mismas claves en los dos idiomas', () => {
        expect(Object.keys(en.password).sort()).toEqual(Object.keys(es.password).sort());
    });

    it('formulario de cambio de contraseña en inglés', () => {
        render(<LocaleProvider locale="en"><ChangePassword /></LocaleProvider>);
        expect(screen.getByLabelText('Current password')).toBeTruthy();
        expect(screen.getByLabelText('New password')).toBeTruthy();
        expect(screen.getByLabelText('Repeat the new password')).toBeTruthy();
        expect(screen.getByText('Between 8 and 128 characters.')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Change password' })).toBeTruthy();
    });

    it('en español no cambia', () => {
        render(<LocaleProvider locale="es"><ChangePassword /></LocaleProvider>);
        expect(screen.getByLabelText('Contraseña actual')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Cambiar contraseña' })).toBeTruthy();
    });

    it('los mensajes de las acciones siguen el idioma elegido', async () => {
        getLocale.mockResolvedValue('en');
        requireAuthenticatedUser.mockResolvedValue({ id: 'u1' });
        await expect(changePassword({ currentPassword: '', newPassword: 'x', confirmPassword: 'x' }))
            .resolves.toMatchObject({ success: false, message: 'Enter your current password.' });
        await expect(changePassword({ currentPassword: 'abcdefgh', newPassword: 'abcdefgh', confirmPassword: 'abcdefgh' }))
            .resolves.toMatchObject({ message: 'The new password must be different from the current one.' });
        await expect(resetPasswordWithToken({ token: ' ', newPassword: 'x', confirmPassword: 'x' }))
            .resolves.toMatchObject({ message: 'This link is invalid or has expired. Ask for a new one.' });
        await expect(requestPasswordReset('a@b.c')).resolves.toMatchObject({ emailConfigured: false });
        expect((await requestPasswordReset('a@b.c')).message).toMatch(/^Password reset by email isn't set up/);
    });

    it('sin idioma de la petición quedan en español', async () => {
        getLocale.mockRejectedValue(new Error('fuera de petición'));
        requireAuthenticatedUser.mockResolvedValue({ id: 'u1' });
        await expect(changePassword({ currentPassword: '', newPassword: 'x', confirmPassword: 'x' }))
            .resolves.toMatchObject({ message: 'Introduce tu contraseña actual.' });
    });
});
