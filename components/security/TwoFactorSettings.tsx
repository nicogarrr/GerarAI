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
import { useT } from '@/lib/i18n/client';

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
    const t = useT();
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
                toast.error(t('security.twoFactor.enableFailed'), { description: result.error ?? t('security.twoFactor.tryAgain') });
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
                toast.error(t('security.twoFactor.verifyFailed'), { description: result.error ?? t('security.twoFactor.invalidCode') });
                return;
            }
            setSetup(null);
            setEnabled(true);
            totpForm.reset();
            toast.success(t('security.twoFactor.enabledToast'));
        } finally {
            setBusy(false);
        }
    };

    const handleDisable = async ({ password }: PasswordForm) => {
        setBusy(true);
        try {
            const result = await disableTwoFactor({ password });
            if (!result.success) {
                toast.error(t('security.twoFactor.disableFailed'), { description: result.error ?? t('security.twoFactor.tryAgain') });
                return;
            }
            setEnabled(false);
            passwordForm.reset();
            toast.success(t('security.twoFactor.disabledToast'));
        } finally {
            setBusy(false);
        }
    };

    const copyBackupCodes = async () => {
        if (!setup) return;
        try {
            await navigator.clipboard.writeText(setup.backupCodes.join('\n'));
            toast.success(t('security.twoFactor.codesCopied'));
        } catch {
            toast.error(t('security.twoFactor.codesCopyFailed'));
        }
    };

    const copyTotpSecret = async () => {
        if (!totpSecret) return;
        try {
            await navigator.clipboard.writeText(totpSecret);
            toast.success(t('security.twoFactor.keyCopied'));
        } catch {
            toast.error(t('security.twoFactor.keyCopyFailed'));
        }
    };

    return (
        <div className="max-w-xl space-y-6">
            <div>
                <h2 className="text-xl font-semibold text-white">{t('security.twoFactor.title')}</h2>
                <p className="text-sm text-gray-400 mt-1">
                    {t('security.twoFactor.subtitle')}
                </p>
            </div>

            {enabled && (
                <div className="rounded-lg border border-green-800/50 bg-green-950/20 p-4">
                    <p className="text-sm text-green-400 font-medium">{t('security.twoFactor.enabledStatus')}</p>
                    <p className="text-xs text-gray-400 mt-1">
                        {t('security.twoFactor.enabledHint')}
                    </p>
                </div>
            )}

            {!enabled && !setup && (
                <form onSubmit={passwordForm.handleSubmit(handleEnable)} className="space-y-4 rounded-lg border border-gray-800 p-5">
                    <p className="text-sm text-gray-300">{t('security.twoFactor.confirmToEnable')}</p>
                    <InputField
                        name="password"
                        label={t('security.twoFactor.passwordLabel')}
                        placeholder={t('security.twoFactor.passwordPlaceholder')}
                        type="password"
                        register={passwordForm.register}
                        error={passwordForm.formState.errors.password}
                        validation={{ required: t('security.twoFactor.passwordRequired') }}
                    />
                    <Button type="submit" disabled={busy} className="brand-btn">
                        {busy ? t('security.twoFactor.generating') : t('security.twoFactor.enable')}
                    </Button>
                </form>
            )}

            {setup && (
                <div className="space-y-5 rounded-lg border border-gray-800 p-5">
                    <p className="text-sm text-gray-300 font-medium">{t('security.twoFactor.step1')}</p>
                    <div className="flex items-center gap-5">
                        <div
                            className="rounded-lg bg-white p-3"
                            role="img"
                            aria-label={t('security.twoFactor.qrAria')}
                        >
                            <QRCodeSVG value={setup.totpURI} size={160} aria-hidden="true" />
                        </div>
                        <p className="text-xs text-gray-400 max-w-[220px]">
                            {t('security.twoFactor.scanHint')}
                        </p>
                    </div>

                    {totpSecret ? (
                        <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
                            <p className="text-sm text-gray-300 font-medium">{t('security.twoFactor.manualKey')}</p>
                            <p className="mt-1 text-xs text-gray-500">
                                {t('security.twoFactor.manualKeyHint')}
                            </p>
                            <code
                                aria-label={t('security.twoFactor.secretAria')}
                                className="mt-2 block break-all rounded bg-gray-950 p-2 font-mono text-xs text-gray-200 select-all"
                            >
                                {totpSecret}
                            </code>
                            <Button type="button" variant="outline" size="sm" className="mt-2" onClick={copyTotpSecret}>
                                {t('security.twoFactor.copyKey')}
                            </Button>
                        </div>
                    ) : null}

                    <div>
                        <p className="text-sm text-gray-300 font-medium">{t('security.twoFactor.step2')}</p>
                        <p className="text-xs text-gray-500 mt-1">
                            {t('security.twoFactor.backupHint')}
                        </p>
                        <div className="mt-2 rounded-md bg-gray-900 border border-gray-800 p-3 font-mono text-xs text-gray-300 grid grid-cols-2 gap-1">
                            {setup.backupCodes.map((code) => (
                                <span key={code}>{code}</span>
                            ))}
                        </div>
                        <Button type="button" variant="outline" size="sm" className="mt-2" onClick={copyBackupCodes}>
                            {t('security.twoFactor.copyCodes')}
                        </Button>
                    </div>

                    <form onSubmit={totpForm.handleSubmit(handleActivate)} className="space-y-4 pt-2">
                        <p className="text-sm text-gray-300 font-medium">{t('security.twoFactor.step3')}</p>
                        <InputField
                            name="totpCode"
                            label={t('security.twoFactor.codeLabel')}
                            placeholder="000000"
                            autoComplete="one-time-code"
                            register={totpForm.register}
                            error={totpForm.formState.errors.totpCode}
                            validation={{
                                required: t('security.twoFactor.codeRequired'),
                                pattern: { value: /^\d{6}$/, message: t('security.twoFactor.codeDigits') },
                            }}
                        />
                        <Button type="submit" disabled={busy} className="brand-btn">
                            {busy ? t('security.twoFactor.verifying') : t('security.twoFactor.enable')}
                        </Button>
                        <button
                            type="button"
                            className="block text-sm text-gray-500 hover:text-gray-300"
                            onClick={() => setSetup(null)}
                        >
                            {t('security.twoFactor.cancel')}
                        </button>
                    </form>
                </div>
            )}

            {enabled && (
                <form onSubmit={passwordForm.handleSubmit(handleDisable)} className="space-y-4 rounded-lg border border-gray-800 p-5">
                    <p className="text-sm text-gray-300">{t('security.twoFactor.confirmToDisable')}</p>
                    <InputField
                        name="password"
                        label={t('security.twoFactor.passwordLabel')}
                        placeholder={t('security.twoFactor.passwordPlaceholder')}
                        type="password"
                        register={passwordForm.register}
                        error={passwordForm.formState.errors.password}
                        validation={{ required: t('security.twoFactor.passwordRequired') }}
                    />
                    <Button type="submit" disabled={busy} variant="destructive" className="w-full sm:w-auto">
                        {busy ? t('security.twoFactor.disabling') : t('security.twoFactor.disable')}
                    </Button>
                </form>
            )}
        </div>
    );
}