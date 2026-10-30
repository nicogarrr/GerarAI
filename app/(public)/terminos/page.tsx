import type { Metadata } from 'next';
import Link from 'next/link';

import { SUPPORT_EMAIL } from '@/lib/config/brand';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: t('landing.terminos.metaTitle'),
        description: t('landing.terminos.metaDescription'),
        // Texto pendiente de validación jurídica por el titular: no se indexa.
        robots: { index: false, follow: false },
        alternates: { canonical: '/terminos' },
    };
}

export default async function TermsPage() {
    const t = await getT();
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">{t('landing.terminos.h1')}</h1>
            <p className="mt-2 text-sm text-gray-500">{t('landing.terminos.lastReview')}</p>

            <div className="mt-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100" role="note">
                <p>{t('landing.terminos.legalNote')}</p>
            </div>

            <article className="mt-8 space-y-6 text-sm leading-7 text-gray-300">
                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s1.title')}</h2>
                    <p>
                        {t('landing.terminos.s1.pPre')}{' '}
                        <a className="text-teal-300 underline" href={`mailto:${SUPPORT_EMAIL}`}>
                            {SUPPORT_EMAIL}
                        </a>
                        .
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s2.title')}</h2>
                    <p>
                        {t('landing.terminos.s2.p1')}
                    </p>
                    <p className="font-medium text-amber-200">
                        {t('landing.terminos.s2.p2')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s3.title')}</h2>
                    <p>
                        {t('landing.terminos.s3.pPre')}{' '}
                        <Link className="text-teal-300 underline" href="/security">/security</Link>
                        {t('landing.terminos.s3.pPost')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s4.title')}</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>{t('landing.terminos.s4.i1')}</li>
                        <li>{t('landing.terminos.s4.i2')}</li>
                        <li>{t('landing.terminos.s4.i3')}</li>
                        <li>{t('landing.terminos.s4.i4')}</li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s5.title')}</h2>
                    <p>
                        {t('landing.terminos.s5.pPre')}{' '}
                        <Link className="text-teal-300 underline" href="/privacidad">{t('landing.terminos.s5.pLink')}</Link>{' '}
                        {t('landing.terminos.s5.pPost')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s6.title')}</h2>
                    <p>
                        {t('landing.terminos.s6.pPre')}
                        <a
                            className="text-teal-300 underline"
                            href="https://github.com/nicogarrr/gerarai"
                            rel="noreferrer"
                            target="_blank"
                        >
                            {t('landing.terminos.s6.pLink')}
                        </a>
                        {t('landing.terminos.s6.pPost')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s7.title')}</h2>
                    <p>
                        {t('landing.terminos.s7.p')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s8.title')}</h2>
                    <p>
                        {t('landing.terminos.s8.pPre')}{' '}
                        <Link className="text-teal-300 underline" href="/security">/security</Link>
                        {t('landing.terminos.s8.pMid')}{' '}
                        <Link className="text-teal-300 underline" href="/privacidad">{t('landing.terminos.s8.pLink')}</Link>
                        {t('landing.terminos.s8.pPost')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s9.title')}</h2>
                    <p>
                        {t('landing.terminos.s9.p')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.terminos.s10.title')}</h2>
                    <p>
                        {t('landing.terminos.s10.p')}
                    </p>
                </section>
            </article>

            <p className="mt-10 text-sm text-gray-500">
                {t('landing.terminos.footer.pre')}{' '}
                <Link className="text-teal-300 underline" href="/privacidad">{t('landing.terminos.footer.link')}</Link>.
            </p>
        </main>
    );
}
