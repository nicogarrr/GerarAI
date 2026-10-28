'use client';

import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import InputField from '@/components/forms/InputField';
import { useForm } from 'react-hook-form';
import {
    activateTwoFactorTotp,
    disableTwoFactor,
    enableTwoFactorTotp,
} from '@/lib/actions/auth.actions';

// qrcode.react (~10 KB gz) solo se usa al activar 2FA, no al abrir /security:
// el QR se pinta tras enviar la contraseña, así que carga diferido. El chunk
// se precarga al enviar el formulario de activación: baja en paralelo con la
// server action y el QR aparece sin espera extra.
const loadQrCode = () => import('qrcode.react').then((mod) => mod.QRCodeSVG);
const QRCodeSVG = dynamic(loadQrCode, {
    loading: () => <span className="block h-[160px] w-[160px] animate-pulse rounded bg-gray-200" aria-hidden="true" />,
});

type Props = {
    initiallyEnabled: boolean;
};

type PasswordForm = { password: string };
type TotpForm = { totpCode: string };

/** Extrae el secreto Base32 del URI otpauth que devuelve el backend. */
function totpSecretFromUri(uri: string): string | null {
    try {
        const parsed = new URL(uri);
        if (parsed.protocol !== 'otpauth:') return null;
        const secret = parsed.searchParams.get('secret')?.trim().toUpperCase();
        return secret || null;
    } catch {
        return null;
    }
}

export default function TwoFactorSettings({ initiallyEnabled }: Props) {
    const [enabled, setEnabled] = useState(initiallyEnabled);
    const [setup, setSetup] = useState<{ totpURI: string; backupCodes: string[] } | null>(null);
    const [busy, setBusy] = useState(false);

    const totpSecret = setup ? totpSecretFromUri(setup.totpURI) : null;

    const passwordForm = useForm<PasswordForm>({ mode: 'onBlur' });
    const totpForm = useForm<TotpForm>({
        defaultValues: { totpCode: '' },
        mode: 'onBlur',
    });

    const handleEnable = async ({ password }: PasswordForm) => {
        setBusy(true);
        // Precarga del QR mientras el servidor genera el secreto.
        void loadQrCode();
        try {
            const result = await enableTwoFactorTotp({ password });
            if (!result.success || !result.data?.totpURI) {
                toast.error('No se pudo activar 2FA', { description: result.error ?? 'Inténtalo de nuevo.' });
                return;
            }
            setSetup({
                totpURI: result.data.totpURI,
                backupCodes: result.data.backupCodes ?? [],
            });
            passwordForm.reset();
        } finally {
            setBusy(false);
        }
    };

    const handleActivate = async ({ totpCode }: TotpForm) => {
        setBusy(true);
        try {
            const result = await activateTwoFactorTotp({ totpCode });
            if (!result.success) {
                toast.error('Verificación fallida', { description: result.error ?? 'Código no válido.' });
                return;
            }
            setSetup(null);
            setEnabled(true);
            totpForm.reset();
            toast.success('Verificación en dos pasos activada');
        } finally {
            setBusy(false);
        }
    };

    const handleDisable = async ({ password }: PasswordForm) => {
        setBusy(true);
        try {
            const result = await disableTwoFactor({ password });
            if (!result.success) {
                toast.error('No se pudo desactivar 2FA', { description: result.error ?? 'Inténtalo de nuevo.' });
                return;
            }
            setEnabled(false);
            passwordForm.reset();
            toast.success('Verificación en dos pasos desactivada');
        } finally {
            setBusy(false);
        }
    };

    const copyBackupCodes = async () => {
        if (!setup) return;
        try {
            await navigator.clipboard.writeText(setup.backupCodes.join('\n'));
            toast.success('Códigos de respaldo copiados');
        } catch {
            toast.error('No se pudieron copiar — anótalos a mano');
        }
    };

    const copyTotpSecret = async () => {
        if (!totpSecret) return;
        try {
            await navigator.clipboard.writeText(totpSecret);
            toast.success('Clave de configuración copiada');
        } catch {
            toast.error('No se pudo copiar — selecciona la clave y cópiala a mano');
        }
    };

    return (
        <div className="max-w-xl space-y-6">
            <div>
                <h2 className="text-xl font-semibold text-white">Verificación en dos pasos (2FA)</h2>
                <p className="text-sm text-gray-400 mt-1">
                    Protege tu cuenta con un código temporal de una app de autenticación
                    (Google Authenticator, 1Password, Authy&hellip;).
                </p>
            </div>

            {enabled && (
                <div className="rounded-lg border border-green-800/50 bg-green-950/20 p-4">
                    <p className="text-sm text-green-400 font-medium">✓ La verificación en dos pasos está activada</p>
                    <p className="text-xs text-gray-400 mt-1">
                        Cada inicio de sesión pedirá el código de tu app además de la contraseña.
                    </p>
                </div>
            )}

            {!enabled && !setup && (
                <form onSubmit={passwordForm.handleSubmit(handleEnable)} className="space-y-4 rounded-lg border border-gray-800 p-5">
                    <p className="text-sm text-gray-300">Para activar 2FA, confirma tu contraseña:</p>
                    <InputField
                        name="password"
                        label="Tu contraseña"
                        placeholder="Introduce tu contraseña"
                        type="password"
                        register={passwordForm.register}
                        error={passwordForm.formState.errors.password}
                        validation={{ required: 'La contraseña es obligatoria' }}
                    />
                    <Button type="submit" disabled={busy} className="brand-btn">
                        {busy ? 'Generando…' : 'Activar 2FA'}
                    </Button>
                </form>
            )}

            {setup && (
                <div className="space-y-5 rounded-lg border border-gray-800 p-5">
                    <p className="text-sm text-gray-300 font-medium">1 · Escanea el código QR</p>
                    <div className="flex items-center gap-5">
                        <div
                            className="rounded-lg bg-white p-3"
                            role="img"
                            aria-label="Código QR para configurar la verificación en dos pasos"
                        >
                            <QRCodeSVG value={setup.totpURI} size={160} aria-hidden="true" />
                        </div>
                        <p className="text-xs text-gray-400 max-w-[220px]">
                            Abre tu app de autenticación y escanea este código, o introduce
                            la clave manualmente desde los ajustes de la app.
                        </p>
                    </div>

                    {totpSecret ? (
                        <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
                            <p className="text-sm text-gray-300 font-medium">Clave manual (Base32)</p>
                            <p className="mt-1 text-xs text-gray-500">
                                Si no puedes escanear el QR, elige «introducir clave manualmente» en tu app
                                y pega esta clave. Es el mismo secreto, no un código de un solo uso.
                            </p>
                            <code
                                aria-label="Clave TOTP en Base32"
                                className="mt-2 block break-all rounded bg-gray-950 p-2 font-mono text-xs text-gray-200 select-all"
                            >
                                {totpSecret}
                            </code>
                            <Button type="button" variant="outline" size="sm" className="mt-2" onClick={copyTotpSecret}>
                                Copiar clave
                            </Button>
                        </div>
                    ) : null}

                    <div>
                        <p className="text-sm text-gray-300 font-medium">2 · Guarda tus códigos de respaldo</p>
                        <p className="text-xs text-gray-500 mt-1">
                            Estos códigos de un solo uso te permiten recuperar el acceso si
                            pierdes tu autenticador. Guárdalos en un lugar seguro.
                        </p>
                        <div className="mt-2 rounded-md bg-gray-900 border border-gray-800 p-3 font-mono text-xs text-gray-300 grid grid-cols-2 gap-1">
                            {setup.backupCodes.map((code) => (
                                <span key={code}>{code}</span>
                            ))}
                        </div>
                        <Button type="button" variant="outline" size="sm" className="mt-2" onClick={copyBackupCodes}>
                            Copiar códigos
                        </Button>
                    </div>

                    <form onSubmit={totpForm.handleSubmit(handleActivate)} className="space-y-4 pt-2">
                        <p className="text-sm text-gray-300 font-medium">3 · Confirma el código</p>
                        <InputField
                            name="totpCode"
                            label="Código de 6 dígitos"
                            placeholder="000000"
                            autoComplete="one-time-code"
                            register={totpForm.register}
                            error={totpForm.formState.errors.totpCode}
                            validation={{
                                required: 'El código es obligatorio',
                                pattern: { value: /^\d{6}$/, message: 'El código debe tener 6 dígitos' },
                            }}
                        />
                        <Button type="submit" disabled={busy} className="brand-btn">
                            {busy ? 'Verificando…' : 'Activar 2FA'}
                        </Button>
                        <button
                            type="button"
                            className="block text-sm text-gray-500 hover:text-gray-300"
                            onClick={() => setSetup(null)}
                        >
                            Cancelar
                        </button>
                    </form>
                </div>
            )}

            {enabled && (
                <form onSubmit={passwordForm.handleSubmit(handleDisable)} className="space-y-4 rounded-lg border border-gray-800 p-5">
                    <p className="text-sm text-gray-300">Para desactivar 2FA, confirma tu contraseña:</p>
                    <InputField
                        name="password"
                        label="Tu contraseña"
                        placeholder="Introduce tu contraseña"
                        type="password"
                        register={passwordForm.register}
                        error={passwordForm.formState.errors.password}
                        validation={{ required: 'La contraseña es obligatoria' }}
                    />
                    <Button type="submit" disabled={busy} variant="destructive" className="w-full sm:w-auto">
                        {busy ? 'Desactivando…' : 'Desactivar 2FA'}
                    </Button>
                </form>
            )}
        </div>
    );
}