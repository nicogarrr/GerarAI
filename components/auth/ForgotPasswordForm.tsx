'use client';

import { useState } from 'react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { requestPasswordReset } from '@/lib/actions/password.actions';

export default function ForgotPasswordForm({
    emailConfigured,
    supportEmail,
}: {
    emailConfigured: boolean;
    supportEmail: string;
}) {
    const [email, setEmail] = useState('');
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [isError, setIsError] = useState(false);

    if (!emailConfigured) {
        return (
            <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100">
                <p className="font-medium">El restablecimiento por correo no está disponible.</p>
                <p className="mt-1">
                    Este despliegue no tiene SMTP configurado, así que no se enviará ningún
                    enlace. Si ya has iniciado sesión, cambia la contraseña desde{' '}
                    <Link className="underline" href="/security">Seguridad</Link>.
                    {supportEmail ? (
                        <> Si no puedes entrar, escribe a <a className="underline" href={`mailto:${supportEmail}`}>{supportEmail}</a>.</>
                    ) : (
                        <> Si no puedes entrar, usa el canal de contacto publicado en la página legal.</>
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
            setMessage('No se pudo procesar la solicitud. Inténtalo de nuevo en unos minutos.');
            setIsError(true);
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="space-y-4" onSubmit={onSubmit}>
            <div>
                <Label htmlFor="forgot-email">Email de la cuenta</Label>
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
                {busy ? 'Enviando…' : 'Enviar enlace de restablecimiento'}
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
                <Link className="underline hover:text-teal-300" href="/sign-in">Volver a iniciar sesión</Link>
            </p>
        </form>
    );
}
