import type { Metadata } from 'next';
import Link from 'next/link';

import { SUPPORT_EMAIL } from '@/lib/config/brand';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: t('landing.privacidad.metaTitle'),
        description: t('landing.privacidad.metaDescription'),
        // Texto pendiente de validación jurídica por el titular: no se indexa.
        robots: { index: false, follow: false },
        alternates: { canonical: '/privacidad' },
    };
}

export default async function PrivacyPage() {
    const t = await getT();
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">{t('landing.privacidad.h1')}</h1>
            <p className="mt-2 text-sm text-gray-500">{t('landing.privacidad.lastReview')}</p>

            <div className="mt-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100" role="note">
                <p>
                    {t('landing.privacidad.legalNote')}
                </p>
            </div>

            <article className="prose prose-invert mt-8 max-w-none space-y-6 text-sm leading-7 text-gray-300">
                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s1.title')}</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>{t('landing.privacidad.s1.identity')}</li>
                        <li>
                            {t('landing.privacidad.s1.contact')}{' '}
                            <a className="text-teal-300 underline" href={`mailto:${SUPPORT_EMAIL}`}>
                                {SUPPORT_EMAIL}
                            </a>
                        </li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s2.title')}</h2>
                    <p>
                        {t('landing.privacidad.s2.p1')}
                    </p>
                    <p>
                        {t('landing.privacidad.s2.p2')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s3.title')}</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            {t('landing.privacidad.s3.i1')}
                        </li>
                        <li>
                            {t('landing.privacidad.s3.i2')}
                        </li>
                        <li>{t('landing.privacidad.s3.i3')}</li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s4.title')}</h2>
                    <p>{t('landing.privacidad.s4.intro')}</p>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            <strong>{t('landing.privacidad.s4.llmStrong')}</strong>
                            {t('landing.privacidad.s4.llmRest')}
                        </li>
                        <li>
                            <strong>{t('landing.privacidad.s4.marketStrong')}</strong>
                            {t('landing.privacidad.s4.marketRest')}
                        </li>
                        <li>
                            <strong>{t('landing.privacidad.s4.hostingStrong')}</strong>
                            {t('landing.privacidad.s4.hostingRest')}
                        </li>
                        <li>
                            <strong>{t('landing.privacidad.s4.storageStrong')}</strong>
                            {t('landing.privacidad.s4.storageRest')}
                        </li>
                        <li>
                            <strong>{t('landing.privacidad.s4.backupsStrong')}</strong>
                            {t('landing.privacidad.s4.backupsRest')}
                        </li>
                        <li>
                            <strong>{t('landing.privacidad.s4.mailStrong')}</strong>
                            {t('landing.privacidad.s4.mailRest')}
                        </li>
                    </ul>
                    <p className="mt-2">
                        {t('landing.privacidad.s4.transfers')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s5.title')}</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            {t('landing.privacidad.s5.docs1')}{' '}<code>FINANCIAL_DOCUMENT_RETENTION_DAYS</code>
                            {t('landing.privacidad.s5.docs2')}
                        </li>
                        <li>
                            {t('landing.privacidad.s5.telemetry1')}{' '}<code>CHAT_TELEMETRY_RETENTION_DAYS</code>
                            {t('landing.privacidad.s5.telemetry2')}
                        </li>
                        <li>
                            {t('landing.privacidad.s5.access1')}{' '}
                            <code>ACCESS_REQUEST_RETENTION_DAYS</code>
                            {t('landing.privacidad.s5.access2')}
                        </li>
                        <li>
                            {t('landing.privacidad.s5.backups')}
                        </li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s6.title')}</h2>
                    <p>
                        {t('landing.privacidad.s6.p1Pre')}{' '}
                        <Link className="text-teal-300 underline" href="/security">/security</Link>{' '}
                        {t('landing.privacidad.s6.p1Post')}
                    </p>
                    <p>
                        {t('landing.privacidad.s6.p2Pre')}{' '}
                        <a
                            className="text-teal-300 underline"
                            href="https://www.aepd.es"
                            rel="noreferrer"
                            target="_blank"
                        >
                            www.aepd.es
                        </a>
                        {t('landing.privacidad.s6.p2Post')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s7.title')}</h2>
                    <p>
                        {t('landing.privacidad.s7.p1')}
                    </p>
                    <p>
                        {t('landing.privacidad.s7.p2Pre')}{' '}
                        <a
                            className="text-teal-300 underline"
                            href="https://github.com/nicogarrr/gerarai"
                            rel="noreferrer"
                            target="_blank"
                        >
                            github.com/nicogarrr/gerarai
                        </a>
                        {t('landing.privacidad.s7.p2Post')}
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">{t('landing.privacidad.s8.title')}</h2>
                    <p>
                        {t('landing.privacidad.s8.p')}
                    </p>
                </section>
            </article>

            <p className="mt-10 text-sm text-gray-500">
                {t('landing.privacidad.footer.pre')}{' '}
                <Link className="text-teal-300 underline" href="/terminos">{t('landing.privacidad.footer.terms')}</Link>{' '}
                {t('landing.privacidad.footer.mid')}{' '}
                <Link className="text-teal-300 underline" href="/metodologia">{t('landing.privacidad.footer.methodology')}</Link>.
            </p>
        </main>
    );
}
