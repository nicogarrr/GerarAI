'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

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
            <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100">
                <p className="font-medium">{t('auth.resetPassword.invalidLinkTitle')}</p>
                <p className="mt-1">
                    {t('auth.resetPassword.invalidLinkPrefix')} <Link className="underline" href="/forgot-password">{t('auth.resetPassword.invalidLinkLink')}</Link>.
                </p>
            </div>
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
            {message ? (
                <p
                    className={`text-sm ${isError ? 'text-red-300' : 'text-teal-200'}`}
                    role={isError ? 'alert' : 'status'}
                >
                    {message}
                </p>
            ) : null}
            <p className="text-sm text-gray-500">
                <Link className="underline hover:text-teal-300" href="/sign-in">{t('auth.resetPassword.goToSignIn')}</Link>
            </p>
        </form>
    );
}
