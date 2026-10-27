import { headers } from 'next/headers';
import { redirect } from 'next/navigation';

import { REQUESTED_PATH_HEADER, signInPathFor } from '@/lib/auth/safe-redirect';

/**
 * Redirección a `/sign-in` desde un layout o página de servidor cuando la
 * sesión no es válida (caducada o revocada con la cookie aún presente: el
 * middleware la deja pasar y la valida el servidor).
 *
 * Conserva la ruta pedida en `?next=` como hace el middleware, para volver a
 * ella tras el login en lugar de caer en /inicio.
 */
export async function redirectToSignIn(): Promise<never> {
    let requested: string | null = null;
    try {
        requested = (await headers()).get(REQUESTED_PATH_HEADER);
    } catch {
        // Fuera de una petición (build, tests): sin ruta que recordar.
    }
    redirect(signInPathFor(requested));
}
