import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getAuth, callAuthEndpoint, authApi } = vi.hoisted(() => ({
    getAuth: vi.fn(),
    callAuthEndpoint: vi.fn(),
    authApi: {
        enableTwoFactor: vi.fn(),
        verifyTOTP: vi.fn(),
        disableTwoFactor: vi.fn(),
        getSession: vi.fn(),
        signOut: vi.fn(),
    },
}));
vi.mock('@/lib/better-auth/auth', () => ({ getAuth }));
vi.mock('@/lib/auth/endpoint', () => ({ callAuthEndpoint }));
vi.mock('next/headers', () => ({
    headers: vi.fn(async () => new Headers()),
    cookies: vi.fn(async () => ({ get: () => undefined })),
}));

import { AppError } from '@/lib/types/errors';
import {
    signUpWithEmail,
    signInWithEmail,
    verifyTwoFactorTotp,
    enableTwoFactorTotp,
    activateTwoFactorTotp,
    disableTwoFactor,
    getTwoFactorStatus,
    signOut,
} from '@/lib/actions/auth.actions';

const signUpInput = {
    email: 'nico@example.com',
    password: 'super-secreta',
    fullName: 'Nico',
    country: 'ES',
    investmentGoals: 'largo plazo',
    riskTolerance: 'moderada',
    preferredIndustry: 'tecnología',
} as unknown as SignUpFormData;

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    getAuth.mockResolvedValue({ api: authApi });
});

describe('signUpWithEmail', () => {
    it('sin auth disponible -> AUTH_UNAVAILABLE sin llamar al endpoint', async () => {
        getAuth.mockResolvedValue(null);
        const result = await signUpWithEmail(signUpInput);
        expect(result).toEqual({ success: false, error: expect.stringContaining('autenticación no está disponible') });
        expect(callAuthEndpoint).not.toHaveBeenCalled();
    });

    it('registro OK: el perfil inversor viaja al endpoint y la respuesta no serializa tokens', async () => {
        callAuthEndpoint.mockResolvedValue({ twoFactorRedirect: false });
        const result = await signUpWithEmail(signUpInput);
        expect(callAuthEndpoint).toHaveBeenCalledWith('/sign-up/email', {
            email: 'nico@example.com',
            password: 'super-secreta',
            name: 'Nico',
            country: 'ES',
            investmentGoals: 'largo plazo',
            riskTolerance: 'moderada',
            preferredIndustry: 'tecnología',
        });
        expect(result).toEqual({ success: true });
    });

    it('error AUTH_ENDPOINT_* devuelve la copia segura del endpoint sin reinterpretarla', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('Este email ya está registrado. Inicia sesión.', 'AUTH_ENDPOINT_USER_ALREADY_EXISTS', 422));
        const result = await signUpWithEmail(signUpInput);
        expect(result).toEqual({ success: false, error: 'Este email ya está registrado. Inicia sesión.' });
    });

    it('error genérico con "email" -> copia de email registrado', async () => {
        callAuthEndpoint.mockRejectedValue(new Error('User with this email already exists'));
        expect(await signUpWithEmail(signUpInput)).toEqual({ success: false, error: 'Este email ya está registrado. Inicia sesión.' });
    });

    it('error genérico con "password" -> copia de 8 caracteres', async () => {
        callAuthEndpoint.mockRejectedValue(new Error('Password too short'));
        expect(await signUpWithEmail(signUpInput)).toEqual({ success: false, error: 'La contraseña debe tener al menos 8 caracteres.' });
    });

    it('error desconocido -> mensaje seguro (nunca el texto crudo con secretos)', async () => {
        callAuthEndpoint.mockRejectedValue(new Error('fetch https://api.example.com?token=SECRET123 failed'));
        const result = await signUpWithEmail(signUpInput);
        expect(result.success).toBe(false);
        expect(result.error).not.toContain('SECRET123');
    });
});

describe('signInWithEmail', () => {
    const input = { email: 'nico@example.com', password: 'super-secreta' } as SignInFormData;

    it('login OK -> success sin serializar la sesión', async () => {
        callAuthEndpoint.mockResolvedValue({ twoFactorRedirect: false });
        expect(await signInWithEmail(input)).toEqual({ success: true });
    });

    it('respuesta con twoFactorRedirect -> señal 2FA, no éxito (el usuario tiene sesión pendiente)', async () => {
        callAuthEndpoint.mockResolvedValue({ twoFactorRedirect: true });
        expect(await signInWithEmail(input)).toEqual({ success: false, twoFactorRequired: true });
    });

    it('error 403 con "two factor" -> señal 2FA', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('Two factor authentication required', 'UNKNOWN_ERROR', 403));
        expect(await signInWithEmail(input)).toEqual({ success: false, twoFactorRequired: true });
    });

    it('error AUTH_ENDPOINT_* pasa la copia segura del endpoint', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('Email o contraseña no válidos. Revisa los datos e inténtalo de nuevo.', 'AUTH_ENDPOINT_ERROR', 401));
        expect(await signInWithEmail(input)).toEqual({ success: false, error: 'Email o contraseña no válidos. Revisa los datos e inténtalo de nuevo.' });
    });

    it('error genérico con "Invalid" -> copia de credenciales inválidas', async () => {
        callAuthEndpoint.mockRejectedValue(new Error('Invalid credentials'));
        expect(await signInWithEmail(input)).toEqual({ success: false, error: 'Email o contraseña no válidos. Revisa los datos e inténtalo de nuevo.' });
    });
});

describe('verifyTwoFactorTotp', () => {
    const input = { email: 'nico@example.com', password: 'x', totpCode: '123456' };

    it('código válido -> success', async () => {
        callAuthEndpoint.mockResolvedValue({});
        expect(await verifyTwoFactorTotp(input)).toEqual({ success: true });
        expect(callAuthEndpoint).toHaveBeenCalledWith('/two-factor/verify-totp', { code: '123456' });
    });

    it('429/503 -> mensaje seguro del servicio, no el genérico de código', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('Demasiados intentos. Espera un momento antes de volver a intentarlo.', 'AUTH_ENDPOINT_ERROR', 429));
        expect(await verifyTwoFactorTotp(input)).toEqual({ success: false, error: 'Demasiados intentos. Espera un momento antes de volver a intentarlo.' });
    });

    it('código incorrecto -> mensaje de código no válido', async () => {
        callAuthEndpoint.mockRejectedValue(new AppError('INVALID_TOTP', 'AUTH_ENDPOINT_ERROR', 401));
        expect(await verifyTwoFactorTotp(input)).toEqual({ success: false, error: 'Código de autenticación no válido. Inténtalo de nuevo.' });
    });
});

describe('2FA setup y estado', () => {
    it('enableTwoFactorTotp expone solo totpURI y backupCodes', async () => {
        authApi.enableTwoFactor.mockResolvedValue({ totpURI: 'otpauth://totp/x', backupCodes: ['a', 'b'], token: 'RAW_SESSION_TOKEN' });
        const result = await enableTwoFactorTotp({ password: 'super-secreta' });
        expect(result).toEqual({ success: true, data: { totpURI: 'otpauth://totp/x', backupCodes: ['a', 'b'] } });
        expect(JSON.stringify(result)).not.toContain('RAW_SESSION_TOKEN');
    });

    it('enableTwoFactorTotp con contraseña incorrecta -> error seguro', async () => {
        authApi.enableTwoFactor.mockRejectedValue(new AppError('Invalid password', 'AUTH_ENDPOINT_ERROR', 401));
        const result = await enableTwoFactorTotp({ password: 'mala' });
        expect(result.success).toBe(false);
        expect(result.error).toBeTruthy();
    });

    it('activateTwoFactorTotp con código erróneo -> mensaje de código no válido', async () => {
        authApi.verifyTOTP.mockRejectedValue(new AppError('INVALID_TOTP', 'AUTH_ENDPOINT_ERROR', 400));
        expect(await activateTwoFactorTotp({ totpCode: '000000' })).toEqual({ success: false, error: 'Código de autenticación no válido. Inténtalo de nuevo.' });
    });

    it('disableTwoFactor OK -> success; fallo -> error seguro', async () => {
        authApi.disableTwoFactor.mockResolvedValue({});
        expect(await disableTwoFactor({ password: 'super-secreta' })).toEqual({ success: true });
        authApi.disableTwoFactor.mockRejectedValue(new AppError('Invalid password', 'AUTH_ENDPOINT_ERROR', 401));
        expect((await disableTwoFactor({ password: 'mala' })).success).toBe(false);
    });

    it('getTwoFactorStatus refleja twoFactorEnabled del usuario en sesión', async () => {
        authApi.getSession.mockResolvedValue({ user: { twoFactorEnabled: true } });
        expect(await getTwoFactorStatus()).toEqual({ success: true, enabled: true });
        authApi.getSession.mockResolvedValue({ user: {} });
        expect(await getTwoFactorStatus()).toEqual({ success: true, enabled: false });
        authApi.getSession.mockResolvedValue(null);
        expect(await getTwoFactorStatus()).toEqual({ success: true, enabled: false });
    });
});

describe('signOut', () => {
    it('cierra la sesión', async () => {
        authApi.signOut.mockResolvedValue({});
        expect(await signOut()).toEqual({ success: true });
        expect(authApi.signOut).toHaveBeenCalled();
    });

    it('fallo al cerrar -> mensaje accionable', async () => {
        authApi.signOut.mockRejectedValue(new Error('network down'));
        expect(await signOut()).toEqual({ success: false, error: 'No se pudo cerrar la sesión. Recarga la página e inténtalo de nuevo.' });
    });
});
