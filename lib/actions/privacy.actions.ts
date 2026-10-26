'use server';

import { headers } from 'next/headers';

import { getAuth } from '@/lib/better-auth/auth';
import { callAuthEndpoint } from '@/lib/auth/endpoint';
import {
    DELETE_REAUTH_HEADER,
    createDeleteReauthToken,
} from '@/lib/auth/delete-reauth';
import { deleteAuthAccountResidue } from '@/lib/better-auth/account-residue';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { connectToDatabase } from '@/database/mongoose';
import { env } from '@/lib/env';
import { AccessRequest } from '@/database/models/access-request.model';
import {
    ManualDemoAccount,
    ManualDemoTrade,
} from '@/database/models/manual-demo.model';
import { AppError, toAppError } from '@/lib/types/errors';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

export type AccountExportResult = {
    filename: string;
    contentType: string;
    content: string;
};

export type PrivacyActionResult = {
    success: boolean;
    message: string;
};

function backendUrl(path: '/api/privacy/export' | '/api/privacy/account'): URL {
    const url = new URL(path, BACKEND_URL);
    if (url.origin !== new URL(BACKEND_URL).origin) {
        throw new AppError('Backend de privacidad mal configurado', 'CONFIG_ERROR', 500);
    }
    return url;
}

async function sessionProfile(fallback: {
    id: string;
    email?: string | null;
    name?: string | null;
}): Promise<Record<string, unknown>> {
    try {
        const auth = await getAuth();
        const session = await auth.api.getSession({ headers: await headers() });
        const user = session?.user as Record<string, unknown> | undefined;
        return {
            email: (user?.email as string | undefined) ?? fallback.email ?? null,
            name: (user?.name as string | undefined) ?? fallback.name ?? null,
            country: (user?.country as string | undefined) ?? null,
            investmentGoals: (user?.investmentGoals as string | undefined) ?? null,
            riskTolerance: (user?.riskTolerance as string | undefined) ?? null,
            preferredIndustry: (user?.preferredIndustry as string | undefined) ?? null,
        };
    } catch {
        return {
            email: fallback.email ?? null,
            name: fallback.name ?? null,
        };
    }
}

/**
 * Descarga el JSON completo del tenant firmado y le añade el perfil que vive
 * en Mongo/Better Auth. El backend solo devuelve datos del principal firmado.
 */
export async function exportAccountData(): Promise<AccountExportResult> {
    const user = await requireAuthenticatedUser();
    const path = '/api/privacy/export';
    const identityHeaders = await researchIdentityHeaders({ method: 'GET', path });
    let response: Response;
    try {
        response = await fetch(backendUrl(path), {
            headers: { ...identityHeaders },
            cache: 'no-store',
            signal: AbortSignal.timeout(60_000),
        });
    } catch {
        throw new AppError(
            'El servicio de datos no responde. Inténtalo de nuevo en unos minutos.',
            'PRIVACY_BACKEND_UNAVAILABLE',
            503,
        );
    }
    if (!response.ok) {
        console.error(`[exportAccountData] research engine respondió ${response.status}`);
        throw new AppError(
            `La exportación falló (${response.status}). Inténtalo de nuevo.`,
            'PRIVACY_EXPORT_FAILED',
            response.status,
        );
    }
    const payload = await response.json() as Record<string, unknown>;
    const profile = await sessionProfile(user);
    const content = JSON.stringify(
        {
            ...payload,
            profile: {
                ...(typeof payload.profile === 'object' && payload.profile !== null
                    ? payload.profile as Record<string, unknown>
                    : {}),
                account: profile,
            },
        },
        null,
        2,
    );
    const stamp = new Date().toISOString().slice(0, 10);
    return {
        filename: `gerarai-datos-${stamp}.json`,
        contentType: 'application/json',
        content,
    };
}

/**
 * Borrado autoservicio con reautenticación y confirmación explícita.
 *
 * 1) La frase debe coincidir con el email de la sesión (servidor, no cliente).
 * 2) Se verifica la contraseña ANTES de destruir nada.
 * 3) El backend borra Postgres + MinIO/Garage + Qdrant y solo devuelve 200 si
 *    no quedan datos. Si falla, no se toca Mongo ni la cuenta.
 * 4) Se limpian datos auxiliares de Mongo y, por último, Better Auth borra
 *    user/sessions/accounts (revocando todas las sesiones).
 */
export async function deleteAccount(input: {
    confirmation: string;
    password: string;
}): Promise<PrivacyActionResult> {
    const user = await requireAuthenticatedUser();
    const email = (user.email ?? '').trim().toLowerCase();
    if (!email) {
        return {
            success: false,
            message: 'La sesión no tiene email; no se puede confirmar el borrado.',
        };
    }
    if (input.confirmation.trim().toLowerCase() !== email) {
        return {
            success: false,
            message: 'Escribe exactamente el email de tu cuenta para confirmar.',
        };
    }
    if (!input.password) {
        return { success: false, message: 'Introduce tu contraseña para reautenticarte.' };
    }

    try {
        await callAuthEndpoint('/verify-password', { password: input.password });
    } catch (error: unknown) {
        const appError = toAppError(error);
        console.error('Account deletion reauth failed:', appError.code);
        return {
            success: false,
            message: appError.statusCode === 429
                ? 'Demasiados intentos. Espera un momento antes de volver a intentarlo.'
                : appError.statusCode === 400 || appError.statusCode === 401
                    ? 'Contraseña incorrecta. No se ha borrado nada.'
                    : 'No se pudo verificar la sesión. No se ha borrado nada; inténtalo de nuevo.',
        };
    }

    const path = '/api/privacy/account';
    const body = JSON.stringify({ confirmation: 'ELIMINAR MI CUENTA' });
    const identityHeaders = await researchIdentityHeaders({
        method: 'DELETE',
        path,
        body,
    });
    let response: Response;
    try {
        response = await fetch(backendUrl(path), {
            method: 'DELETE',
            headers: {
                ...identityHeaders,
                'Content-Type': 'application/json',
            },
            body,
            cache: 'no-store',
            signal: AbortSignal.timeout(60_000),
        });
    } catch {
        return {
            success: false,
            message:
                'El servicio de datos no responde; no se ha borrado nada. '
                + 'Inténtalo de nuevo en unos minutos.',
        };
    }
    if (!response.ok) {
        console.error(`[deleteAccount] research engine respondió ${response.status}`);
        return {
            success: false,
            message:
                response.status === 502
                    ? 'No se pudo limpiar todo el almacenamiento; no se ha confirmado el borrado. Reinténtalo.'
                    : 'No se pudo borrar la cuenta. No se ha eliminado nada. Inténtalo de nuevo.',
        };
    }

    try {
        await connectToDatabase();
        await Promise.all([
            AccessRequest.deleteMany({ email }),
            ManualDemoAccount.deleteMany({ userId: user.id }),
            ManualDemoTrade.deleteMany({ userId: user.id }),
        ]);
    } catch (error: unknown) {
        // Los datos de investigación ya no existen; no se finge que la cuenta
        // sigue intacta. Se aborta antes de borrar el usuario para poder
        // reintentar el resto sin recrear el tenant.
        console.error('Mongo account cleanup failed:', toAppError(error).code);
        return {
            success: false,
            message:
                'Los datos de investigación se han borrado, pero no se pudieron limpiar '
                + 'los datos auxiliares. Vuelve a intentarlo para terminar de cerrar la cuenta.',
        };
    }

    try {
        const reauthToken = createDeleteReauthToken(
            user.id,
            env.BETTER_AUTH_SECRET,
        );
        await callAuthEndpoint(
            '/delete-user',
            { password: input.password },
            { [DELETE_REAUTH_HEADER]: reauthToken },
        );
    } catch (error: unknown) {
        console.error('Better Auth user deletion failed:', toAppError(error).code);
        return {
            success: false,
            message:
                'Tus datos de investigación se han borrado, pero la cuenta de acceso sigue '
                + 'activa. Vuelve a intentarlo para cerrarla definitivamente.',
        };
    }

    try {
        const mongoose = await connectToDatabase();
        const db = mongoose?.connection?.db;
        if (!db) {
            throw new Error('MongoDB is required to clean account residue');
        }
        await deleteAuthAccountResidue(db, user);
    } catch (error: unknown) {
        console.error('Mongo auth residue cleanup failed:', toAppError(error).code);
        return {
            success: false,
            message:
                'La cuenta de acceso se ha cerrado, pero no se pudieron borrar todos '
                + 'los datos de doble factor. Contacta con soporte para completar la limpieza.',
        };
    }

    return {
        success: true,
        message: 'Cuenta y datos eliminados. Se han cerrado todas las sesiones.',
    };
}
