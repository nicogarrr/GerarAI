'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { changePassword } from '@/lib/actions/password.actions';
import { useT } from '@/lib/i18n/client';

export default function ChangePassword() {
    const t = useT();
    const [currentPassword, setCurrentPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [busy, setBusy] = useState(false);

    const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setBusy(true);
        try {
            const result = await changePassword({
                currentPassword,
                newPassword,
                confirmPassword,
            });
            if (!result.success) {
                toast.error(t('security.password.errorTitle'), { description: result.message });
                return;
            }
            setCurrentPassword('');
            setNewPassword('');
            setConfirmPassword('');
            toast.success(t('security.password.successTitle'), { description: result.message });
        } catch {
            toast.error(t('security.password.errorTitle'), {
                description: t('security.password.sessionUnavailable'),
            });
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="space-y-4" onSubmit={onSubmit}>
            <div>
                <Label htmlFor="current-password">{t('security.password.currentLabel')}</Label>
                <Input
                    autoComplete="current-password"
                    className="mt-2 min-h-11"
                    id="current-password"
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    required
                    type="password"
                    value={currentPassword}
                />
            </div>
            <div>
                <Label htmlFor="new-password">{t('security.password.newLabel')}</Label>
                <Input
                    autoComplete="new-password"
                    className="mt-2 min-h-11"
                    id="new-password"
                    minLength={8}
                    onChange={(event) => setNewPassword(event.target.value)}
                    required
                    type="password"
                    value={newPassword}
                />
                <p className="mt-1 text-xs text-gray-500">{t('security.password.lengthHint')}</p>
            </div>
            <div>
                <Label htmlFor="confirm-password">{t('security.password.confirmLabel')}</Label>
                <Input
                    autoComplete="new-password"
                    className="mt-2 min-h-11"
                    id="confirm-password"
                    minLength={8}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    required
                    type="password"
                    value={confirmPassword}
                />
            </div>
            <Button disabled={busy} type="submit">
                {busy ? t('security.password.submitting') : t('security.password.submit')}
            </Button>
        </form>
    );
}
