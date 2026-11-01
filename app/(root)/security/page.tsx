import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAuthenticatedUser } from "@/lib/auth/require-user";
import { redirectToSignIn } from "@/lib/auth/sign-in-redirect";
import { getTwoFactorStatus } from "@/lib/actions/auth.actions";
import { isPasswordResetEmailConfigured } from "@/lib/auth/email";
import TwoFactorSettings from "@/components/security/TwoFactorSettings";
import ChangePassword from "@/components/security/ChangePassword";
import PrivacySettings from "@/components/security/PrivacySettings";
import InstallApp from "@/components/pwa/InstallApp";
import { Panel } from "@/components/ui/panel";
import { getT } from '@/lib/i18n/server';

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return { title: t('security.page.metaTitle') };
}

export default async function SecurityPage() {
    let user;
    try {
        user = await requireAuthenticatedUser();
    } catch {
        return redirectToSignIn();
    }

    const t = await getT();
    const status = await getTwoFactorStatus();
    const emailResetAvailable = isPasswordResetEmailConfigured();

    return (
        <main id="content" tabIndex={-1} className="space-y-8">
            <div>
                <h1 className="text-2xl font-bold text-white">{t('security.page.title')}</h1>
                <p className="text-sm text-gray-400 mt-1">
                    {t('security.page.accountOf')} <span className="text-gray-200">{user.email}</span>.
                </p>
            </div>

            {status.success ? (
                <TwoFactorSettings initiallyEnabled={Boolean(status.enabled)} />
            ) : (
                <section
                    role="alert"
                    data-testid="two-factor-unavailable"
                    className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200"
                >
                    {t('security.page.twoFactorUnknown')}
                </section>
            )}

            <Panel title={t('security.page.passwordTitle')} description={t('security.page.passwordDescription')}>
                <div className="space-y-4">
                    <ChangePassword />
                    {emailResetAvailable ? (
                        <p className="text-sm text-gray-400">
                            {t('security.page.forgotBefore')}{' '}
                            <Link className="text-teal-300 hover:underline" href="/forgot-password">
                                {t('security.page.forgotLink')}
                            </Link>
                            .
                        </p>
                    ) : (
                        <p className="text-sm text-amber-200">
                            {t('security.page.noSmtp')}
                        </p>
                    )}
                </div>
            </Panel>

            <Panel
                title={t('security.page.dataTitle')}
                description={t('security.page.dataDescription')}
            >
                <PrivacySettings email={user.email ?? ''} />
            </Panel>

            <InstallApp />
        </main>
    );
}
