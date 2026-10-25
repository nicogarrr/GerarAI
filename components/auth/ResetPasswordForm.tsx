'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { resetPasswordWithToken } from '@/lib/actions/password.actions';

export default function ResetPasswordForm({
    token,
    linkError,
}: {
    token: string;
    linkError: boolean;
}) {
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
                <p className="font-medium">El enlace no es válido o ha caducado.</p>
                <p className="mt-1">
                    Pide uno nuevo en <Link className="underline" href="/forgot-password">restablecer contraseña</Link>.
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
            setMessage('No se pudo guardar la contraseña. Inténtalo de nuevo.');
            setIsError(true);
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="space-y-4" onSubmit={onSubmit}>
            <div>
                <Label htmlFor="reset-new-password">Contraseña nueva</Label>
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
                <p className="mt-1 text-xs text-gray-500">Entre 8 y 128 caracteres.</p>
            </div>
            <div>
                <Label htmlFor="reset-confirm-password">Repite la contraseña nueva</Label>
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
                {busy ? 'Guardando…' : done ? 'Contraseña actualizada' : 'Guardar contraseña'}
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
                <Link className="underline hover:text-teal-300" href="/sign-in">Ir a iniciar sesión</Link>
            </p>
        </form>
    );
}
