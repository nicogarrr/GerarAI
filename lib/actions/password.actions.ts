'use server';

import { headers } from 'next/headers';

import { getAuth } from '@/lib/better-auth/auth';
import { isPasswordResetEmailConfigured } from '@/lib/auth/email';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
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

const RESET_REQUESTED =
    'Si ese email tiene cuenta, recibirás un enlace para restablecer la contraseña. Revisa también la carpeta de spam.';

export async function requestPasswordReset(email: string): Promise<PasswordActionResult> {
    if (!isPasswordResetEmailConfigured()) {
        return {
            success: false,
            emailConfigured: false,
            message:
                'El restablecimiento por correo no está configurado en este despliegue. '
                + 'Inicia sesión y cambia la contraseña desde Seguridad, o contacta con soporte.',
        };
    }
    const normalized = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) {
        return { success: false, emailConfigured: true, message: 'Introduce un email válido.' };
    }
    try {
        const auth = await getAuth();
        await auth.api.requestPasswordReset({
            body: {
                email: normalized,
                redirectTo: `${siteUrl()}/reset-password`,
            },
            headers: await headers(),
        });
    } catch (error: unknown) {
        // No se revela si el email existe ni el detalle del proveedor.
        console.error('Password reset request failed:', toAppError(error).code);
    }
    return { success: true, emailConfigured: true, message: RESET_REQUESTED };
}

export async function resetPasswordWithToken(input: {
    token: string;
    newPassword: string;
    confirmPassword: string;
}): Promise<PasswordActionResult> {
    if (!input.token.trim()) {
        return {
            success: false,
            message: 'El enlace no es válido o ha caducado. Pide uno nuevo.',
        };
    }
    if (input.newPassword.length < 8 || input.newPassword.length > 128) {
        return {
            success: false,
            message: 'La contraseña debe tener entre 8 y 128 caracteres.',
        };
    }
    if (input.newPassword !== input.confirmPassword) {
        return { success: false, message: 'Las contraseñas no coinciden.' };
    }
    try {
        const auth = await getAuth();
        await auth.api.resetPassword({
            body: { newPassword: input.newPassword, token: input.token.trim() },
            headers: await headers(),
        });
        return {
            success: true,
            message: 'Contraseña actualizada. Inicia sesión con la nueva contraseña.',
        };
    } catch (error: unknown) {
        console.error('Password reset failed:', toAppError(error).code);
        return {
            success: false,
            message: 'El enlace no es válido o ha caducado. Pide uno nuevo.',
        };
    }
}

export async function changePassword(input: {
    currentPassword: string;
    newPassword: string;
    confirmPassword: string;
}): Promise<PasswordActionResult> {
    await requireAuthenticatedUser();
    if (!input.currentPassword) {
        return { success: false, message: 'Introduce tu contraseña actual.' };
    }
    if (input.newPassword.length < 8 || input.newPassword.length > 128) {
        return {
            success: false,
            message: 'La contraseña nueva debe tener entre 8 y 128 caracteres.',
        };
    }
    if (input.newPassword !== input.confirmPassword) {
        return { success: false, message: 'Las contraseñas nuevas no coinciden.' };
    }
    if (input.newPassword === input.currentPassword) {
        return { success: false, message: 'La contraseña nueva debe ser distinta de la actual.' };
    }
    try {
        const auth = await getAuth();
        await auth.api.changePassword({
            body: {
                currentPassword: input.currentPassword,
                newPassword: input.newPassword,
                // Mantiene la sesion actual y revoca las demas.
                revokeOtherSessions: true,
            },
            headers: await headers(),
        });
        return {
            success: true,
            message: 'Contraseña cambiada. Las demás sesiones se han cerrado.',
        };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Change password failed:', appError.code);
        return {
            success: false,
            message: appError.statusCode === 429
                ? 'Demasiados intentos. Espera un momento antes de volver a intentarlo.'
                : 'No se pudo cambiar la contraseña. Revisa que la actual sea correcta.',
        };
    }
}
