import Link from 'next/link';
import type { Metadata } from 'next';
import { ArrowRight } from 'lucide-react';

import LandingMockup from '@/components/landing/LandingMockup';
import { Button } from '@/components/ui/button';
import { isPublicSignUpOpen } from '@/lib/config/product';
import { getLocale, getT } from '@/lib/i18n/server';

/**
 * Metadatos de la landing.
 *
 * Viven aquí y la página los reexporta: `app/(public)/page.tsx` es
 * `export { default, metadata } from '@/components/landing/PublicLanding'`.
 * El título no incluye la marca porque la plantilla de `app/layout.tsx` ya
 * añade «| GerarAI».
 */
export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    const locale = await getLocale();
    return {
        title: t('landing.hero.metaTitle'),
        description: t('landing.hero.metaDescription'),
        alternates: { canonical: '/' },
        openGraph: {
            type: 'website',
            locale: locale === 'en' ? 'en_US' : 'es_ES',
            siteName: 'GerarAI',
            title: t('landing.hero.ogTitle'),
            description: t('landing.hero.ogDescription'),
        },
    };
}

export default async function PublicLanding() {
    const t = await getT();
    const signUpOpen = isPublicSignUpOpen();

    return (
        <main id="content" tabIndex={-1} className="w-full overflow-x-clip">
            <section className="container pb-16 pt-10 text-left sm:pb-28 sm:pt-20 sm:text-center">
                <p className="inline-flex max-w-full items-center gap-2 rounded-full border border-teal-400/30 bg-teal-400/10 px-4 py-2 text-[10px] font-semibold uppercase leading-5 tracking-[0.16em] text-teal-300 sm:text-xs sm:tracking-[0.2em]">
                    {t('landing.hero.kicker')}
                </p>
                <h1 className="mx-auto mt-4 max-w-3xl text-balance text-[clamp(2.7rem,11vw,3.1rem)] font-semibold leading-[1.12] tracking-[-0.015em] text-gray-100 sm:mt-6 sm:text-7xl">
                    {t('landing.hero.titlePre')}<span className="italic text-teal-300" style={{ fontFamily: "var(--font-editorial), Georgia, serif" }}>{t('landing.hero.titleHighlight')}</span>{t('landing.hero.titlePost')}
                </h1>
                <p className="mx-auto mt-5 max-w-2xl text-base leading-7 text-gray-400 sm:mt-6 sm:text-balance sm:text-lg sm:leading-8">
                    {t('landing.hero.subtitle')}
                </p>
                <div className="mt-7 flex flex-col items-stretch gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-center">
                    {signUpOpen ? (
                        <Button asChild size="lg">
                            <Link href="/sign-up">
                                {t('landing.hero.ctaStart')}
                                <ArrowRight aria-hidden="true" />
                            </Link>
                        </Button>
                    ) : (
                        <Button asChild size="lg">
                            <Link href="/sign-up">
                                {t('landing.hero.ctaAccess')}
                                <ArrowRight aria-hidden="true" />
                            </Link>
                        </Button>
                    )}
                    <Button asChild size="lg" variant="outline">
                        <Link href="/metodologia">{t('landing.hero.ctaMethodology')}</Link>
                    </Button>
                </div>

                <LandingMockup />

                <p className="mx-auto mt-16 max-w-xl text-xs text-gray-500">
                    {t('landing.hero.caption')}
                </p>
            </section>
        </main>
    );
}
