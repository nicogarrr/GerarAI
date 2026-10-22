'use server';

import { getAuth } from "@/lib/better-auth/auth";
import { headers } from "next/headers";
import { callAuthEndpoint } from "@/lib/auth/endpoint";
import { AuthenticationError, toAppError, getSafeErrorMessage } from "@/lib/types/errors";
import { ERROR_MESSAGES } from "@/lib/constants";

export const signUpWithEmail = async ({ email, password, fullName, country, investmentGoals, riskTolerance, preferredIndustry }: SignUpFormData): Promise<{ success: boolean; error?: string }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        // El perfil inversor viaja en el propio sign-up (additionalFields de
        // better-auth, sin migraciones SQL) en vez de perderse en el destructuring.
        await callAuthEndpoint('/sign-up/email', { email, password, name: fullName, country, investmentGoals, riskTolerance, preferredIndustry });

        // The auth endpoint delivers the session in HttpOnly cookies. Never serialize
        // Better Auth's response: it also contains the raw bearer session token.
        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        // The endpoint maps documented status/code pairs to safe Spanish copy.
        // Do not reinterpret that structured result by English substrings.
        if (appError.code.startsWith('AUTH_ENDPOINT_') || appError.code === 'AUTH_UNAVAILABLE') {
            return { success: false, error: getSafeErrorMessage(appError) };
        }


        // Mensajes de error más específicos
        let errorMessage: string = ERROR_MESSAGES.AUTH_FAILED;

        if (appError.message.includes('email') || appError.message.includes('Email')) {
            errorMessage = 'Este email ya está registrado. Inicia sesión.';
        } else if (appError.message.includes('password') || appError.message.includes('Password')) {
            errorMessage = 'La contraseña debe tener al menos 8 caracteres.';
        } else if (appError.message.includes('unavailable') || appError.message.includes('temporarily')) {
            errorMessage = ERROR_MESSAGES.AUTH_UNAVAILABLE;
        } else {
            errorMessage = getSafeErrorMessage(error);
        }

        console.error('Sign up failed:', appError);
        return { success: false, error: errorMessage };
    }
}

export const signInWithEmail = async ({ email, password }: SignInFormData): Promise<{ success: boolean; error?: string; twoFactorRequired?: boolean }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        const response = await callAuthEndpoint('/sign-in/email', { email, password });

        // better-auth (plugin twoFactor) NO lanza con 2FA activo: responde 200 con
        // `twoFactorRedirect: true`, sin sesion, solo con la cookie pendiente de
        // 2FA. Tratarlo como exito mandaba a /inicio sin sesion y el middleware
        // devolvia a /sign-in: un usuario con 2FA no podia entrar nunca.
        if ((response as { twoFactorRedirect?: boolean } | null)?.twoFactorRedirect) {
            return { success: false, twoFactorRequired: true };
        }

        // The auth endpoint delivers the session in HttpOnly cookies. Never serialize
        // Better Auth's response: it also contains the raw bearer session token.
        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        // The endpoint maps documented status/code pairs to safe Spanish copy.
        // Do not reinterpret that structured result by English substrings.
        if (appError.code.startsWith('AUTH_ENDPOINT_') || appError.code === 'AUTH_UNAVAILABLE') {
            return { success: false, error: getSafeErrorMessage(appError) };
        }


        // better-auth blocks sign-in with HTTP 403 when the account has 2FA
        // enabled. Surface a dedicated signal so the UI can show the TOTP step.
        if (
            appError.message.toLowerCase().includes('two factor')
            || appError.message.toLowerCase().includes('2fa')
        ) {
            return { success: false, twoFactorRequired: true };
        }

        let errorMessage: string = ERROR_MESSAGES.AUTH_FAILED;

        if (appError.message.includes('Invalid') || appError.message.includes('invalid')) {
            errorMessage = 'Email o contraseña no válidos. Revisa los datos e inténtalo de nuevo.';
        } else if (appError.message.includes('unavailable') || appError.message.includes('temporarily')) {
            errorMessage = ERROR_MESSAGES.AUTH_UNAVAILABLE;
        } else {
            errorMessage = getSafeErrorMessage(error);
        }

        console.error('Sign in failed:', appError);
        return { success: false, error: errorMessage };
    }
}

export const verifyTwoFactorTotp = async ({ email, password, totpCode }: { email: string; password: string; totpCode: string }): Promise<{ success: boolean; error?: string }> => {
    void email; void password; // the pending 2FA session is carried by the cookies
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        await callAuthEndpoint('/two-factor/verify-totp', { code: totpCode });

        // The auth endpoint delivers the session in HttpOnly cookies. Never serialize
        // Better Auth's response: it also contains the raw bearer session token.
        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('2FA verification failed:', appError);
        return { success: false, error: appError.statusCode === 429 || appError.statusCode === 503
            ? getSafeErrorMessage(appError)
            : 'Código de autenticación no válido. Inténtalo de nuevo.' };
    }
}

export const enableTwoFactorTotp = async ({ password }: { password: string }): Promise<{ success: boolean; data?: { totpURI?: string; backupCodes?: string[] }; error?: string }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        const response = await auth.api.enableTwoFactor({
            body: { password },
            headers: await headers(),
        });

        return {
            success: true,
            data: {
                totpURI: (response as { totpURI?: string })?.totpURI,
                backupCodes: (response as { backupCodes?: string[] })?.backupCodes,
            },
        };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Enable 2FA failed:', appError);
        return { success: false, error: getSafeErrorMessage(error) };
    }
}

export const activateTwoFactorTotp = async ({ totpCode }: { totpCode: string }): Promise<{ success: boolean; error?: string }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        await auth.api.verifyTOTP({
            body: { code: totpCode },
            headers: await headers(),
        });

        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Activate 2FA failed:', appError);
        return { success: false, error: 'Código de autenticación no válido. Inténtalo de nuevo.' };
    }
}

export const disableTwoFactor = async ({ password }: { password: string }): Promise<{ success: boolean; error?: string }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        await auth.api.disableTwoFactor({
            body: { password },
            headers: await headers(),
        });

        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Disable 2FA failed:', appError);
        return { success: false, error: getSafeErrorMessage(error) };
    }
}

export const getTwoFactorStatus = async (): Promise<{ success: boolean; enabled?: boolean; error?: string }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        const session = await auth.api.getSession({ headers: await headers() });
        return {
            success: true,
            enabled: Boolean((session?.user as { twoFactorEnabled?: boolean } | undefined)?.twoFactorEnabled),
        };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('2FA status check failed:', appError);
        return { success: false, error: getSafeErrorMessage(error) };
    }
}

export const signOut = async (): Promise<{ success: boolean; error?: string }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        await auth.api.signOut({ headers: await headers() });
        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Sign out failed:', appError);
        return { success: false, error: 'No se pudo cerrar la sesión. Recarga la página e inténtalo de nuevo.' };
    }
}