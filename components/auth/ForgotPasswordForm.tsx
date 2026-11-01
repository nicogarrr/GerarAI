'use client';

import { useState } from 'react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { requestPasswordReset } from '@/lib/actions/password.actions';
import { useT } from '@/lib/i18n/client';

export default function ForgotPasswordForm({
    emailConfigured,
    supportEmail,
}: {
    emailConfigured: boolean;
    supportEmail: string;
}) {
    const t = useT();
    const [email, setEmail] = useState('');
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [isError, setIsError] = useState(false);

    if (!emailConfigured) {
        return (
            <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100">
                <p className="font-medium">{t('auth.forgotPassword.unavailableTitle')}</p>
                <p className="mt-1">
                    {t('auth.forgotPassword.unavailableBody')}{' '}
                    <Link className="underline" href="/security">{t('auth.forgotPassword.securityLink')}</Link>.
                    {supportEmail ? (
                        <> {t('auth.forgotPassword.unavailableContactPrefix')} <a className="underline" href={`mailto:${supportEmail}`}>{supportEmail}</a>.</>
                    ) : (
                        <> {t('auth.forgotPassword.unavailableHelpPrefix')} <Link className="underline" href="/help">{t('auth.forgotPassword.helpLink')}</Link> {t('auth.forgotPassword.unavailableHelpSuffix')}</>
                    )}
                </p>
            </div>
        );
    }

    const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setBusy(true);
        try {
            const result = await requestPasswordReset(email);
            setMessage(result.message);
            setIsError(!result.success);
        } catch {
            setMessage(t('auth.forgotPassword.requestError'));
            setIsError(true);
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="space-y-4" onSubmit={onSubmit}>
            <div>
                <Label htmlFor="forgot-email">{t('auth.forgotPassword.emailLabel')}</Label>
                <Input
                    autoComplete="email"
                    className="mt-2"
                    id="forgot-email"
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    type="email"
                    value={email}
                />
            </div>
            <Button disabled={busy} type="submit">
                {busy ? t('auth.forgotPassword.submitting') : t('auth.forgotPassword.submit')}
            </Button>
            {message ? (
                <p
                    className={`text-sm ${isError ? 'text-red-300' : 'text-teal-200'}`}
                    role={isError ? 'alert' : 'status'}
                >
                    {message}
                </p>
            ) : null}
            <p className="text-sm text-gray-500">
                <Link className="underline hover:text-teal-300" href="/sign-in">{t('auth.forgotPassword.backToSignIn')}</Link>
            </p>
        </form>
    );
}
