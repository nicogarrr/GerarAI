import { readSessionWhenCookies } from "@/lib/anonymous-session";
import { publicSans } from "@/lib/public-fonts";
import Link from "next/link";
import React from "react";
import {headers} from "next/headers";
import {redirect} from "next/navigation";
import {getAuth} from "@/lib/better-auth/auth";
import {GerarAIWordmark} from "@/components/GerarAIWordmark";
import {LineChart} from "lucide-react";
import {productChain, productModules} from "@/lib/config/product";
import {getT} from "@/lib/i18n/server";

// Forzar renderizado dinámico porque usa headers() para verificar sesión
export const dynamic = 'force-dynamic';
export const revalidate = 0;

const Layout = async ({ children }: { children : React.ReactNode }) => {
    const t = await getT();
    const browserTestBypass = process.env.E2E_AUTH_BYPASS === '1' && process.env.NODE_ENV !== 'production';
    if (!browserTestBypass) {
        const requestHeaders = await headers();
        const session = await readSessionWhenCookies(requestHeaders, async () => {
            const auth = await getAuth();
            return auth.api.getSession({ headers: requestHeaders });
        });
        if (session?.user) redirect('/inicio');
    }
    return (
        <main className={`auth-layout ${publicSans.className}`}>
            <section className="auth-left-section !px-6 sm:!px-8 lg:!px-12 xl:!px-20 scrollbar-hide-default">
                {/* Tope de ancho: sin el, en pantallas ultrawide (2560px) el
                    formulario se estiraba a ~1150px y las lineas de texto
                    ilegibles. */}
                <div className="mx-auto flex w-full max-w-md flex-col">
                    <Link href="/" className="auth-logo !mb-8 flex items-center gap-2 lg:!mb-12">
                        <GerarAIWordmark />
                    </Link>

                    <div className="flex-1 pb-6 lg:pb-8">
                        {children}
                    </div>

                    {/* Registro y acceso: la aceptación de las condiciones debe
                        estar a la vista sin depender del pie público, porque
                        este layout es independiente de `(public)`. */}
                    <nav aria-label="Privacidad y condiciones" className="flex flex-wrap gap-x-4 gap-y-2 pb-8 text-xs text-gray-500">
                        <Link className="inline-flex min-h-11 items-center hover:text-teal-300 hover:underline" href="/privacidad">
                            {t('auth.layout.navPrivacy')}
                        </Link>
                        <Link className="inline-flex min-h-11 items-center hover:text-teal-300 hover:underline" href="/terminos">
                            {t('auth.layout.navTerms')}
                        </Link>
                        <Link className="inline-flex min-h-11 items-center hover:text-teal-300 hover:underline" href="/metodologia">
                            {t('auth.layout.navMethodology')}
                        </Link>
                    </nav>
                </div>
            </section>
            <section className="auth-right-section !hidden lg:!flex">
                <div className="lg:mt-4 lg:mb-16">
                    <blockquote className="auth-blockquote">
                        {t('auth.layout.quote')}
                    </blockquote>
                </div>
                {/* Escala gray del tema, no slate: hasta ahora esta pantalla era
                    la unica con dos grises distintos (slate + gray) a la vez. */}
                <div className="flex-1 rounded-xl border border-gray-700/50 bg-surface-overlay p-6 shadow-2xl shadow-teal-950/20">
                    <div className="mb-6 flex items-start justify-between gap-4">
                        <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-300">{t('auth.layout.workspaceLabel')}</p>
                            <h2 className="mt-2 text-2xl font-semibold text-white">{productChain}</h2>
                        </div>
                        <LineChart aria-hidden="true" className="h-7 w-7 text-teal-300"/>
                    </div>
                    <div className="grid gap-3">
                        {productModules.map(({icon: ItemIcon, title, description}) => (
                                <div className="flex gap-4 rounded-lg border border-gray-700/50 bg-gray-800/50 p-4" key={title}>
                                    <ItemIcon aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-teal-300"/>
                                    <div>
                                        <p className="font-medium text-gray-100">{title}</p>
                                        <p className="mt-1 text-sm leading-6 text-gray-400">{description}</p>
                                    </div>
                                </div>
                        ))}
                    </div>
                </div>
            </section>

        </main>
    )
}
export default Layout
