import { readSessionWhenCookies } from "@/lib/anonymous-session";
import { publicSans, publicEditorial } from "@/lib/public-fonts";
import type { Metadata } from 'next';
import Link from 'next/link';
import React from 'react';
import { headers } from 'next/headers';
import { getAuth } from '@/lib/better-auth/auth';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';
import { Button } from '@/components/ui/button';
import { SUPPORT_EMAIL } from '@/lib/config/brand';
import PublicMobileNav from '@/components/PublicMobileNav';
import { isPublicSignUpOpen } from '@/lib/config/product';

/**
 * Shell de las paginas publicas: landing, metodologia y ayuda.
 *
 * Es un grupo de rutas aparte de `(root)` porque la exigibilidad cambia:
 * `(root)` exige sesion (`requireAuthenticatedUser`) y por eso un visitante sin
 * cuenta no podia ni leer la metodologia.
 *
 * Aqui la sesion NO expulsa a nadie: un usuario que ya ha entrado debe poder
 * leer la ayuda y la metodologia desde el menu de la app sin que le boten a `/`.
 * Solo cambia el CTA de la cabecera ("Iniciar sesion" <-> "Ir a mi panel").
 */

// `headers()` en la comprobacion de sesion obliga a render dinamico.
export const dynamic = 'force-dynamic';
export const revalidate = 0;

/**
 * La raiz declara `robots: { index: false }` porque la app autenticada es una
 * herramienta privada. Los metadatos anidados reemplazan campos, asi que
 * declarar aqui `robots` devuelve el indice SOLO a este arbol: `/`,
 * `/metodologia` y `/help`. El resto de la app sigue heredando el noindex de
 * `app/layout.tsx`.
 */
export const metadata: Metadata = {
    robots: { index: true, follow: true },
};

const legalLinks = [
    { href: '/metodologia', label: 'Metodología' },
    { href: '/help', label: 'Ayuda' },
    { href: '/privacidad', label: 'Privacidad' },
    { href: '/terminos', label: 'Términos' },
];

const Layout = async ({ children }: { children: React.ReactNode }) => {
    // Mismo criterio que `app/(auth)/layout.tsx`: en los e2e con
    // E2E_AUTH_BYPASS se acepta que no haya sesion real. El `.catch` importa:
    // si Mongo no responde, estas paginas deben seguir leyendose. Una caida de
    // base de datos no puede convertir estas paginas en un 500.
    const browserTestBypass = process.env.E2E_AUTH_BYPASS === '1' && process.env.NODE_ENV !== 'production';
    let signedIn = false;
    if (!browserTestBypass) {
        const requestHeaders = await headers();
        const session = await readSessionWhenCookies(requestHeaders, async () => {
            const auth = await getAuth().catch(() => null);
            return auth ? auth.api.getSession({ headers: requestHeaders }).catch(() => null) : null;
        });
        signedIn = Boolean(session?.user);
    }

    const signUpOpen = isPublicSignUpOpen() && !signedIn;

    return (
        <div className={`public-shell ${publicSans.className} ${publicEditorial.variable}`}>
            <a href="#content" className="skip-link">Saltar al contenido</a>

            <header className="sticky top-3 z-50 sm:top-4">
                <div className="container">
                    <div className="public-header-inner rounded-2xl sm:rounded-full border border-gray-700/60 bg-surface-1/80 px-3 min-[360px]:px-4 shadow-lg shadow-black/30 backdrop-blur">
                    <Link href="/" className="flex min-h-11 shrink-0 items-center" aria-label="GerarAI, inicio">
                        <GerarAIWordmark />
                    </Link>
                    <nav aria-label="Páginas de GerarAI" className="public-nav">
                        {legalLinks.map((link) => (
                            <Link key={link.href} href={link.href} className="public-nav-link">
                                {link.label}
                            </Link>
                        ))}
                    </nav>
                    <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
                        {signedIn ? (
                            <Button asChild className="h-11" size="sm">
                                <Link href="/inicio">Ir a mi panel</Link>
                            </Button>
                        ) : (
                            <>
                                <Button asChild className="h-11" size="sm" variant="outline">
                                    <Link href="/sign-in">Iniciar sesión</Link>
                                </Button>
                                {signUpOpen ? (
                                    <Button asChild className="h-11 hidden sm:inline-flex" size="sm">
                                        <Link href="/sign-up">Crear cuenta</Link>
                                    </Button>
                                ) : null}
                            </>
                        )}
                        <PublicMobileNav
                            links={legalLinks}
                            cta={signUpOpen ? { href: '/sign-up', label: 'Crear cuenta' } : undefined}
                        />
                    </div>
                    </div>
                </div>
            </header>

            {/* Cada pagina publica declara su unico <main id="content">; el
                layout no añade otro landmark ni envuelve a los hijos. */}
            <div className="public-content">{children}</div>

            <footer className="public-footer">
                <div className="container public-footer-inner">
                    <div className="max-w-sm">
                        <p className="font-medium text-gray-300">GerarAI</p>
                        <p className="mt-1">
                            Herramienta educativa de análisis: GerarAI no da asesoramiento de inversión y
                            las decisiones son tuyas.
                        </p>
                        <p className="mt-1 text-xs">
                            Gráficos interactivos por{' '}
                            <a className="inline-flex min-h-11 items-center public-footer-link underline" href="https://www.tradingview.com/" rel="noreferrer" target="_blank">
                                TradingView
                            </a>
                            .
                        </p>
                    </div>
                    <nav aria-label="Enlaces del pie" className="flex flex-col items-start gap-2 sm:items-end">
                        {legalLinks.map((link) => (
                            <Link key={link.href} href={link.href} className="inline-flex min-h-11 items-center public-footer-link">
                                {link.label}
                            </Link>
                        ))}
                        {SUPPORT_EMAIL && (
                            <a href={`mailto:${SUPPORT_EMAIL}`} className="inline-flex min-h-11 items-center public-footer-link">
                                {SUPPORT_EMAIL}
                            </a>
                        )}
                    </nav>
                </div>
            </footer>
        </div>
    );
};

export default Layout;
