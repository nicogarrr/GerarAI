import type { Metadata } from 'next';

import ResetPasswordForm from '@/components/auth/ResetPasswordForm';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
    title: t('landing.resetPassword.metaTitle'),
    description: t('landing.resetPassword.metaDescription'),
    robots: { index: false, follow: false },
    };
}

export default async function ResetPasswordPage({
    searchParams,
}: {
    searchParams: Promise<{ token?: string; error?: string }>;
}) {
    const t = await getT();
    const params = await searchParams;
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-lg px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">{t('landing.resetPassword.h1')}</h1>
            <p className="mt-2 text-sm text-gray-400">
                {t('landing.resetPassword.body')}
            </p>
            <div className="mt-8">
                <ResetPasswordForm
                    linkError={Boolean(params.error)}
                    token={params.token ?? ''}
                />
            </div>
        </main>
    );
}
