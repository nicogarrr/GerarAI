import type { Metadata } from 'next';

import ForgotPasswordForm from '@/components/auth/ForgotPasswordForm';
import { isPasswordResetEmailConfigured } from '@/lib/auth/email';
import { SUPPORT_EMAIL } from '@/lib/config/brand';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
    title: t('landing.forgotPassword.metaTitle'),
    description: t('landing.forgotPassword.metaDescription'),
    robots: { index: false, follow: false },
    };
}

export default async function ForgotPasswordPage() {
    const t = await getT();
    const emailConfigured = isPasswordResetEmailConfigured();
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-lg px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">{t('landing.forgotPassword.h1')}</h1>
            {emailConfigured ? (
                <p className="mt-2 text-sm text-gray-400">
                    {t('landing.forgotPassword.bodyConfigured')}
                </p>
            ) : (
                <p className="mt-2 text-sm text-gray-400">
                    {t('landing.forgotPassword.bodyUnconfigured')}
                </p>
            )}
            <div className="mt-8">
                <ForgotPasswordForm
                    emailConfigured={emailConfigured}
                    supportEmail={SUPPORT_EMAIL}
                />
            </div>
        </main>
    );
}
