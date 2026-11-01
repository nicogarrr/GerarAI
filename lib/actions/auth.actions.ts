'use server';

import { getAuth } from "@/lib/better-auth/auth";
import { headers } from "next/headers";
import { callAuthEndpoint } from "@/lib/auth/endpoint";
import { AuthenticationError, toAppError, getSafeErrorMessage } from "@/lib/types/errors";
import { getT } from "@/lib/i18n/server";
import { authEndpointErrorMessage } from "@/lib/auth/endpoint-messages";

export const signUpWithEmail = async ({ email, password, fullName, country, investmentGoals, riskTolerance, preferredIndustry }: SignUpFormData): Promise<{ success: boolean; error?: string; accountStatus?: string }> => {
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
        }

        // El perfil inversor viaja en el propio sign-up (additionalFields de
        // better-auth, sin migraciones SQL) en vez de perderse en el destructuring.
        const response = await callAuthEndpoint('/sign-up/email', { email, password, name: fullName, country, investmentGoals, riskTolerance, preferredIndustry });

        // The auth endpoint delivers the session in HttpOnly cookies. Never serialize
        // Better Auth's response: it also contains the raw bearer session token.
        // accountStatus ('pending' con el alta abierta) enruta a /cuenta-pendiente.
        return { success: true, ...(response.accountStatus ? { accountStatus: response.accountStatus } : {}) };
    } catch (error: unknown) {
        const appError = toAppError(error);
        // The endpoint maps documented status/code pairs to safe copy (chosen language).
        // Do not reinterpret that structured result by English substrings.
        if (appError.code.startsWith('AUTH_ENDPOINT_') || appError.code === 'AUTH_UNAVAILABLE') {
            return { success: false, error: authEndpointErrorMessage(appError, t, getSafeErrorMessage(appError)) };
        }


        // Mensajes de error más específicos
        let errorMessage: string = t('errors.backend.authFailed');

        if (appError.message.includes('email') || appError.message.includes('Email')) {
            errorMessage = t('errors.backend.emailAlreadyRegistered');
        } else if (appError.message.includes('password') || appError.message.includes('Password')) {
            errorMessage = t('errors.backend.passwordTooShort');
        } else if (appError.message.includes('unavailable') || appError.message.includes('temporarily')) {
            errorMessage = t('errors.backend.authUnavailable');
        } else {
            errorMessage = getSafeErrorMessage(error);
        }

        console.error('Sign up failed:', appError);
        return { success: false, error: errorMessage };
    }
}

export const signInWithEmail = async ({ email, password }: SignInFormData): Promise<{ success: boolean; error?: string; twoFactorRequired?: boolean; code?: string }> => {
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
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
        // The endpoint maps documented status/code pairs to safe copy (chosen language).
        // Do not reinterpret that structured result by English substrings.
        if (appError.code.startsWith('AUTH_ENDPOINT_') || appError.code === 'AUTH_UNAVAILABLE') {
            // Código estable para el front solo donde el contrato lo pide
            // (ACCOUNT_PENDING / ACCOUNT_REJECTED enrutan a /cuenta-pendiente);
            // el resto mantiene la forma exacta de siempre.
            const stableCode = appError.code === 'AUTH_ENDPOINT_ACCOUNT_PENDING'
                ? 'ACCOUNT_PENDING'
                : appError.code === 'AUTH_ENDPOINT_ACCOUNT_REJECTED'
                    ? 'ACCOUNT_REJECTED'
                    : undefined;
            return {
                success: false,
                error: authEndpointErrorMessage(appError, t, getSafeErrorMessage(appError)),
                ...(stableCode ? { code: stableCode } : {}),
            };
        }


        // better-auth blocks sign-in with HTTP 403 when the account has 2FA
        // enabled. Surface a dedicated signal so the UI can show the TOTP step.
        if (
            appError.message.toLowerCase().includes('two factor')
            || appError.message.toLowerCase().includes('2fa')
        ) {
            return { success: false, twoFactorRequired: true };
        }

        let errorMessage: string = t('errors.backend.authFailed');

        if (appError.message.includes('Invalid') || appError.message.includes('invalid')) {
            errorMessage = t('errors.backend.invalidCredentialsLong');
        } else if (appError.message.includes('unavailable') || appError.message.includes('temporarily')) {
            errorMessage = t('errors.backend.authUnavailable');
        } else {
            errorMessage = getSafeErrorMessage(error);
        }

        console.error('Sign in failed:', appError);
        return { success: false, error: errorMessage };
    }
}

export const verifyTwoFactorTotp = async ({ email, password, totpCode }: { email: string; password: string; totpCode: string }): Promise<{ success: boolean; error?: string }> => {
    void email; void password; // the pending 2FA session is carried by the cookies
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
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
            : t('errors.backend.invalidTotp') };
    }
}

export const enableTwoFactorTotp = async ({ password }: { password: string }): Promise<{ success: boolean; data?: { totpURI?: string; backupCodes?: string[] }; error?: string }> => {
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
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
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
        }

        await auth.api.verifyTOTP({
            body: { code: totpCode },
            headers: await headers(),
        });

        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Activate 2FA failed:', appError);
        return { success: false, error: t('errors.backend.invalidTotp') };
    }
}

export const disableTwoFactor = async ({ password }: { password: string }): Promise<{ success: boolean; error?: string }> => {
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
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
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
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
    const t = await getT();
    try {
        const auth = await getAuth();
        if (!auth) {
            throw new AuthenticationError(t('errors.backend.authUnavailable'));
        }

        await auth.api.signOut({ headers: await headers() });
        return { success: true };
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Sign out failed:', appError);
        return { success: false, error: t('errors.backend.signOutFailed') };
    }
}