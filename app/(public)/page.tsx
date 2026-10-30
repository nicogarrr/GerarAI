import { readSessionWhenCookies } from "@/lib/anonymous-session";
import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { redirect } from 'next/navigation';

import PublicLanding, { generateMetadata as landingGenerateMetadata } from '@/components/landing/PublicLanding';
import { getAuth } from '@/lib/better-auth/auth';
import { landingTargetForSession } from '@/lib/public/landing-target';

/**
 * Landing publica en `/`.
 *
 * El dashboard autenticado vive en `/inicio` (`app/(root)/inicio/page.tsx`): el
 * App Router no admite dos paginas en la misma ruta, y `/` es la direccion que
 * un visitante desconocido teclea o recibe de un enlace. El cambio de URL es
 * invisible para el usuario con sesion porque el layout publico y el wordmark
 * de la app lo llevan ahi, y `/inicio` es la unica ruta de la app que el menu
 * declara como Inicio.
 *
 * Con sesion iniciada la raiz ya no muestra la landing: redirige a `/inicio`
 * directamente. La sesion caducada resuelve igual que la ausencia de sesion
 * (`getSession` valida contra la base de datos y devuelve null), asi que un
 * usuario con cookie vieja ve la landing con el CTA «Iniciar sesion», no un
 * error. Si la base de datos de auth no responde, la landing tambien se sirve
 * (mismo criterio que el layout publico: una caida no puede convertir una
 * pagina publica en un 500).
 *
 * El resto de paginas publicas (`/metodologia`, `/help`) NO
 * redirigen: un usuario con sesion debe poder leerlas desde el menu.
 */
export const generateMetadata: () => Promise<Metadata> = landingGenerateMetadata;

// `headers()` en la comprobacion de sesion obliga a render dinamico.
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function LandingPage() {
    // Mismo criterio que el layout publico: con E2E_AUTH_BYPASS la landing
    // sigue siendo alcanzable en los tests de navegador.
    const browserTestBypass =
        process.env.E2E_AUTH_BYPASS === '1' && process.env.NODE_ENV !== 'production';
    if (!browserTestBypass) {
        const requestHeaders = await headers();
        const session = await readSessionWhenCookies(requestHeaders, async () => {
            const auth = await getAuth().catch(() => null);
            return auth ? auth.api.getSession({ headers: requestHeaders }).catch(() => null) : null;
        });
        const target = landingTargetForSession(Boolean(session?.user));
        if (target) redirect(target);
    }
    return <PublicLanding />;
}
