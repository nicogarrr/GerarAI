'use server';

import { getAuth } from "@/lib/better-auth/auth";
import { headers } from "next/headers";
import { AuthenticationError, toAppError, getSafeErrorMessage } from "@/lib/types/errors";
import { ERROR_MESSAGES } from "@/lib/constants";

export const signUpWithEmail = async ({ email, password, fullName, country, investmentGoals, riskTolerance, preferredIndustry }: SignUpFormData): Promise<{ success: boolean; data?: unknown; error?: string }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        // El perfil inversor viaja en el propio sign-up (additionalFields de
        // better-auth, sin migraciones SQL) en vez de perderse en el destructuring.
        const response = await auth.api.signUpEmail({ body: { email, password, name: fullName, country, investmentGoals, riskTolerance, preferredIndustry } });

        return { success: true, data: response };
    } catch (error: unknown) {
        const appError = toAppError(error);

        // Mensajes de error más específicos
        let errorMessage: string = ERROR_MESSAGES.AUTH_FAILED;

        if (appError.message.includes('email') || appError.message.includes('Email')) {
            errorMessage = 'This email is already registered. Please sign in instead.';
        } else if (appError.message.includes('password') || appError.message.includes('Password')) {
            errorMessage = 'Password must be at least 8 characters long.';
        } else if (appError.message.includes('unavailable') || appError.message.includes('temporarily')) {
            errorMessage = ERROR_MESSAGES.AUTH_UNAVAILABLE;
        } else {
            errorMessage = getSafeErrorMessage(error);
        }

        console.error('Sign up failed:', appError);
        return { success: false, error: errorMessage };
    }
}

export const signInWithEmail = async ({ email, password }: SignInFormData): Promise<{ success: boolean; data?: unknown; error?: string; twoFactorRequired?: boolean }> => {
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        const response = await auth.api.signInEmail({ body: { email, password } });

        // better-auth (plugin twoFactor) NO lanza con 2FA activo: responde 200 con
        // `twoFactorRedirect: true`, sin sesion, solo con la cookie pendiente de
        // 2FA. Tratarlo como exito mandaba a /inicio sin sesion y el middleware
        // devolvia a /sign-in: un usuario con 2FA no podia entrar nunca.
        if ((response as { twoFactorRedirect?: boolean } | null)?.twoFactorRedirect) {
            return { success: false, twoFactorRequired: true };
        }

        return { success: true, data: response };
    } catch (error: unknown) {
        const appError = toAppError(error);

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
            errorMessage = 'Invalid email or password. Please check your credentials and try again.';
        } else if (appError.message.includes('unavailable') || appError.message.includes('temporarily')) {
            errorMessage = ERROR_MESSAGES.AUTH_UNAVAILABLE;
        } else {
            errorMessage = getSafeErrorMessage(error);
        }

        console.error('Sign in failed:', appError);
        return { success: false, error: errorMessage };
    }
}

export const verifyTwoFactorTotp = async ({ email, password, totpCode }: { email: string; password: string; totpCode: string }): Promise<{ success: boolean; data?: unknown; error?: string }> => {
    void email; void password; // the pending 2FA session is carried by the cookies
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(ERROR_MESSAGES.AUTH_UNAVAILABLE);
        }

        const response = await auth.api.verifyTOTP({
            body: { code: totpCode },
            headers: await headers(),
        });

        return { success: true, data: response };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('2FA verification failed:', appError);
        return { success: false, error: 'Invalid authentication code. Please try again.' };
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
        return { success: false, error: 'Invalid authentication code. Please try again.' };
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
            throw new AuthenticationError('Unable to sign out. Authentication service is unavailable.');
        }

        await auth.api.signOut({ headers: await headers() });
        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Sign out failed:', appError);
        return { success: false, error: 'Unable to sign out. Please refresh the page and try again.' };
    }
}