import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { callAuthEndpoint, isPasswordResetEmailConfigured, requireAuthenticatedUser } = vi.hoisted(() => ({
    callAuthEndpoint: vi.fn(),
    isPasswordResetEmailConfigured: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
}));
vi.mock('@/lib/auth/endpoint', () => ({ callAuthEndpoint }));
vi.mock('@/lib/auth/email', () => ({ isPasswordResetEmailConfigured }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));

import { AppError } from '@/lib/types/errors';
import { requestPasswordReset, resetPasswordWithToken, changePassword } from '@/lib/actions/password.actions';

const ENV_KEYS = ['NEXT_PUBLIC_SITE_URL', 'BETTER_AUTH_URL', 'VERCEL_URL'] as const;

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    isPasswordResetEmailConfigured.mockReturnValue(true);
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    for (const key of ENV_KEYS) delete process.env[key];
});

afterEach(() => {
    for (const key of ENV_KEYS) delete process.env[key];
});

describe('requestPasswordReset', () => {
    it('sin SMTP configurado: no llama al endpoint y lo dice claro', async () => {
        isPasswordResetEmailConfigured.mockReturnValue(false);
        const result = await requestPasswordReset('nico@example.com');
        expect(result.success).toBe(false);
        expect(result.emailConfigured).toBe(false);
        expect(result.message).toContain('no está configurado');
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('email inválido: valida antes de llamar al endpoint', async () => {
        for (const bad of ['sin-arroba', 'a@b', '@example.com', 'a b@example.com']) {
            const result = await requestPasswordReset(bad);
            expect(result).toEqual({ success: false, emailConfigured: true, message: 'Introduce un email válido.' });
        }
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('normaliza el email (trim + minúsculas) y construye el redirectTo sin barra duplicada', async () => {
        process.env.NEXT_PUBLIC_SITE_URL = 'https://gerarai.example/';
        callAuthEndpoint.mockResolvedValue({});
        const result = await requestPasswordReset('  NICO@Example.COM  ');
        expect(callAuthEndpoint).toHaveBeenCalledWith('/request-password-reset', {
            email: 'nico@example.com',
            redirectTo: 'https://gerarai.example/reset-password',
        });
        expect(result.success).toBe(true);
        expect(result.emailConfigured).toBe(true);
    });

    it('aunque el endpoint falle responde lo mismo: no revela si el email existe ni el detalle', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('SMTP auth failed user=secret', 'AUTH_ENDPOINT_ERROR', 500));
        const result = await requestPasswordReset('nico@example.com');
        expect(result.success).toBe(true);
        expect(result.message).toContain('Si ese email tiene cuenta');
        expect(result.message).not.toContain('secret');
    });
});

describe('resetPasswordWithToken', () => {
    const base = { token: 'tok123', newPassword: 'nueva-secreta', confirmPassword: 'nueva-secreta' };

    it('token vacío -> enlace caducado, sin llamar al endpoint', async () => {
        const result = await resetPasswordWithToken({ ...base, token: '   ' });
        expect(result.success).toBe(false);
        expect(result.message).toContain('caducado');
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('contraseña fuera de rango (7 y 129) -> error de longitud', async () => {
        expect((await resetPasswordWithToken({ ...base, newPassword: '1234567', confirmPassword: '1234567' })).message)
            .toBe('La contraseña debe tener entre 8 y 128 caracteres.');
        const larga = 'a'.repeat(129);
        expect((await resetPasswordWithToken({ ...base, newPassword: larga, confirmPassword: larga })).message)
            .toBe('La contraseña debe tener entre 8 y 128 caracteres.');
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('contraseñas distintas -> no coinciden', async () => {
        const result = await resetPasswordWithToken({ ...base, confirmPassword: 'otra-distinta' });
        expect(result).toEqual({ success: false, message: 'Las contraseñas no coinciden.' });
    });

    it('OK: envía el token recortado y confirma el cambio', async () => {
        callAuthEndpoint.mockResolvedValue({});
        const result = await resetPasswordWithToken({ ...base, token: '  tok123  ' });
        expect(callAuthEndpoint).toHaveBeenCalledWith('/reset-password', { newPassword: 'nueva-secreta', token: 'tok123' });
        expect(result).toEqual({ success: true, message: 'Contraseña actualizada. Inicia sesión con la nueva contraseña.' });
    });

    it('endpoint rechaza -> enlace caducado sin filtrar el motivo real', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('TOKEN_EXPIRED detail', 'AUTH_ENDPOINT_ERROR', 400));
        const result = await resetPasswordWithToken(base);
        expect(result).toEqual({ success: false, message: 'El enlace no es válido o ha caducado. Pide uno nuevo.' });
    });
});

describe('changePassword', () => {
    const base = { currentPassword: 'actual-secreta', newPassword: 'nueva-secreta', confirmPassword: 'nueva-secreta' };

    it('exige usuario autenticado antes de validar nada', async () => {
        requireAuthenticatedUser.mockRejectedValue(new AppError('No autenticado', 'AUTH_ERROR', 401));
        await expect(changePassword(base)).rejects.toThrow('No autenticado');
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('sin contraseña actual -> error sin llamar al endpoint', async () => {
        expect(await changePassword({ ...base, currentPassword: '' })).toEqual({ success: false, message: 'Introduce tu contraseña actual.' });
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('nueva igual a la actual -> error específico', async () => {
        expect(await changePassword({ ...base, newPassword: base.currentPassword, confirmPassword: base.currentPassword }))
            .toEqual({ success: false, message: 'La contraseña nueva debe ser distinta de la actual.' });
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('OK: revoca las demás sesiones y mantiene la actual', async () => {
        callAuthEndpoint.mockResolvedValue({});
        const result = await changePassword(base);
        expect(callAuthEndpoint).toHaveBeenCalledWith('/change-password', {
            currentPassword: 'actual-secreta',
            newPassword: 'nueva-secreta',
            revokeOtherSessions: true,
        });
        expect(result).toEqual({ success: true, message: 'Contraseña cambiada. Las demás sesiones se han cerrado.' });
    });

    it('429 -> demasiados intentos; 400/401 -> revisa la actual; otro -> genérico', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('rate', 'AUTH_ENDPOINT_ERROR', 429));
        expect((await changePassword(base)).message).toBe('Demasiados intentos. Espera un momento antes de volver a intentarlo.');
        callAuthEndpoint.mockRejectedValue(new AppError('bad', 'AUTH_ENDPOINT_ERROR', 401));
        expect((await changePassword(base)).message).toBe('No se pudo cambiar la contraseña. Revisa que la actual sea correcta.');
        callAuthEndpoint.mockRejectedValue(new AppError('boom', 'AUTH_ENDPOINT_ERROR', 500));
        expect((await changePassword(base)).message).toBe('No se pudo cambiar la contraseña. Inténtalo de nuevo.');
    });
});
