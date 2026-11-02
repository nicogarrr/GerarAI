'use client';

import { useState } from 'react';
import Link from 'next/link';

import { AuthFormFooterLink, AuthFormNotice, AuthFormResult } from '@/components/auth/form-bits';
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
            <AuthFormNotice title={t('auth.forgotPassword.unavailableTitle')}>
                {t('auth.forgotPassword.unavailableBody')}{' '}
                <Link className="underline" href="/security">{t('auth.forgotPassword.securityLink')}</Link>.
                {supportEmail ? (
                    <> {t('auth.forgotPassword.unavailableContactPrefix')} <a className="underline" href={`mailto:${supportEmail}`}>{supportEmail}</a>.</>
                ) : (
                    <> {t('auth.forgotPassword.unavailableHelpPrefix')} <Link className="underline" href="/help">{t('auth.forgotPassword.helpLink')}</Link> {t('auth.forgotPassword.unavailableHelpSuffix')}</>
                )}
            </AuthFormNotice>
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
            <AuthFormResult message={message} isError={isError} />
            <AuthFormFooterLink href="/sign-in">{t('auth.forgotPassword.backToSignIn')}</AuthFormFooterLink>
        </form>
    );
}
