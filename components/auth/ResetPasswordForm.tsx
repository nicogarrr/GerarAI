'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { AuthFormFooterLink, AuthFormNotice, AuthFormResult } from '@/components/auth/form-bits';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { resetPasswordWithToken } from '@/lib/actions/password.actions';
import { useT } from '@/lib/i18n/client';

export default function ResetPasswordForm({
    token,
    linkError,
}: {
    token: string;
    linkError: boolean;
}) {
    const t = useT();
    const router = useRouter();
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [isError, setIsError] = useState(false);
    const [done, setDone] = useState(false);

    if (!token || linkError) {
        return (
            <AuthFormNotice title={t('auth.resetPassword.invalidLinkTitle')}>
                {t('auth.resetPassword.invalidLinkPrefix')} <Link className="underline" href="/forgot-password">{t('auth.resetPassword.invalidLinkLink')}</Link>.
            </AuthFormNotice>
        );
    }

    const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setBusy(true);
        try {
            const result = await resetPasswordWithToken({
                token,
                newPassword,
                confirmPassword,
            });
            setMessage(result.message);
            setIsError(!result.success);
            if (result.success) {
                setDone(true);
                setNewPassword('');
                setConfirmPassword('');
                setTimeout(() => router.push('/sign-in'), 1200);
            }
        } catch {
            setMessage(t('auth.resetPassword.saveError'));
            setIsError(true);
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="space-y-4" onSubmit={onSubmit}>
            <div>
                <Label htmlFor="reset-new-password">{t('auth.resetPassword.newPasswordLabel')}</Label>
                <Input
                    autoComplete="new-password"
                    className="mt-2"
                    disabled={done}
                    id="reset-new-password"
                    minLength={8}
                    onChange={(event) => setNewPassword(event.target.value)}
                    required
                    type="password"
                    value={newPassword}
                />
                <p className="mt-1 text-xs text-gray-500">{t('auth.resetPassword.newPasswordHint')}</p>
            </div>
            <div>
                <Label htmlFor="reset-confirm-password">{t('auth.resetPassword.confirmPasswordLabel')}</Label>
                <Input
                    autoComplete="new-password"
                    className="mt-2"
                    disabled={done}
                    id="reset-confirm-password"
                    minLength={8}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    required
                    type="password"
                    value={confirmPassword}
                />
            </div>
            <Button disabled={busy || done} type="submit">
                {busy ? t('auth.resetPassword.submitting') : done ? t('auth.resetPassword.updated') : t('auth.resetPassword.submit')}
            </Button>
            <AuthFormResult message={message} isError={isError} />
            <AuthFormFooterLink href="/sign-in">{t('auth.resetPassword.goToSignIn')}</AuthFormFooterLink>
        </form>
    );
}
