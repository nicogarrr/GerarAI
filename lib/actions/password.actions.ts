'use server';

import { callAuthEndpoint } from '@/lib/auth/endpoint';
import { isPasswordResetEmailConfigured } from '@/lib/auth/email';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getLocale } from '@/lib/i18n/server';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import { toAppError } from '@/lib/types/errors';

export type PasswordActionResult = {
    success: boolean;
    message: string;
    emailConfigured?: boolean;
};

function siteUrl(): string {
    const vercel = process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : '';
    const raw =
        process.env.NEXT_PUBLIC_SITE_URL
        || process.env.BETTER_AUTH_URL
        || vercel
        || 'http://localhost:3000';
    return raw.replace(/\/$/, '');
}

/**
 * Mensajes en el idioma de la petición (cookie de Ajustes → Idioma). Fuera de
 * una petición (tests, scripts) quedan en español.
 */
async function requestT(): Promise<TranslateFn> {
    let locale: 'es' | 'en' = 'es';
    try {
        locale = await getLocale();
    } catch {
        // Sin contexto de petición: español por defecto.
    }
    return createTranslator(locale);
}

export async function requestPasswordReset(email: string): Promise<PasswordActionResult> {
    const t = await requestT();
    if (!isPasswordResetEmailConfigured()) {
        return {
            success: false,
            emailConfigured: false,
            message: t('security.password.resetNotConfigured'),
        };
    }
    const normalized = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) {
        return { success: false, emailConfigured: true, message: t('security.password.invalidEmail') };
    }
    try {
        await callAuthEndpoint('/request-password-reset', {
            email: normalized,
            redirectTo: `${siteUrl()}/reset-password`,
        });
    } catch (error: unknown) {
        // No se revela si el email existe ni el detalle del proveedor.
        console.error('Password reset request failed:', toAppError(error).code);
    }
    return { success: true, emailConfigured: true, message: t('security.password.resetRequested') };
}

export async function resetPasswordWithToken(input: {
    token: string;
    newPassword: string;
    confirmPassword: string;
}): Promise<PasswordActionResult> {
    const t = await requestT();
    if (!input.token.trim()) {
        return {
            success: false,
            message: t('security.password.invalidLink'),
        };
    }
    if (input.newPassword.length < 8 || input.newPassword.length > 128) {
        return {
            success: false,
            message: t('security.password.lengthError'),
        };
    }
    if (input.newPassword !== input.confirmPassword) {
        return { success: false, message: t('security.password.mismatch') };
    }
    try {
        await callAuthEndpoint('/reset-password', {
            newPassword: input.newPassword,
            token: input.token.trim(),
        });
        return {
            success: true,
            message: t('security.password.resetDone'),
        };
    } catch (error: unknown) {
        console.error('Password reset failed:', toAppError(error).code);
        return {
            success: false,
            message: t('security.password.invalidLink'),
        };
    }
}

export async function changePassword(input: {
    currentPassword: string;
    newPassword: string;
    confirmPassword: string;
}): Promise<PasswordActionResult> {
    await requireAuthenticatedUser();
    const t = await requestT();
    if (!input.currentPassword) {
        return { success: false, message: t('security.password.currentRequired') };
    }
    if (input.newPassword.length < 8 || input.newPassword.length > 128) {
        return {
            success: false,
            message: t('security.password.newLengthError'),
        };
    }
    if (input.newPassword !== input.confirmPassword) {
        return { success: false, message: t('security.password.newMismatch') };
    }
    if (input.newPassword === input.currentPassword) {
        return { success: false, message: t('security.password.sameAsCurrent') };
    }
    try {
        await callAuthEndpoint('/change-password', {
            currentPassword: input.currentPassword,
            newPassword: input.newPassword,
            // Mantiene la sesion actual y revoca las demas.
            revokeOtherSessions: true,
        });
        return {
            success: true,
            message: t('security.password.changed'),
        };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Change password failed:', appError.code);
        return {
            success: false,
            message: appError.statusCode === 429
                ? t('security.password.tooManyAttempts')
                : appError.statusCode === 400 || appError.statusCode === 401
                    ? t('security.password.checkCurrent')
                    : t('security.password.changeFailed'),
        };
    }
}
