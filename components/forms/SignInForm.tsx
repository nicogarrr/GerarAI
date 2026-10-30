'use client';

import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import InputField from '@/components/forms/InputField';
import FooterLink from '@/components/forms/FooterLink';
import {signInWithEmail, verifyTwoFactorTotp} from "@/lib/actions/auth.actions";
import {emailFieldValidation} from "@/lib/validation/email";
import {toast} from "sonner";
import {useRouter} from "next/navigation";
import Link from "next/link";
import React, {useState} from "react";
import {useT} from "@/lib/i18n/client";

type Props = {
    /** Solo se muestra el enlace de recuperación si el despliegue puede enviar correo. */
    passwordResetAvailable: boolean;
    publicSignUpOpen?: boolean;
    /** Ruta interna ya saneada (`safeInternalPath`) a la que volver tras entrar. */
    redirectTo?: string;
};

const SignInForm = ({ passwordResetAvailable, publicSignUpOpen = false, redirectTo = '/inicio' }: Props) => {
    const t = useT();
    const router = useRouter()
    const [twoFactorRequired, setTwoFactorRequired] = useState(false);
    const [pendingCredentials, setPendingCredentials] = useState<{ email: string; password: string } | null>(null);
    const [isVerifying, setIsVerifying] = useState(false);
    const {
        register,
        handleSubmit,
        getValues,
        formState: { errors, isSubmitting },
    } = useForm<SignInFormData>({
        defaultValues: {
            email: '',
            password: '',
        },
        mode: 'onBlur',
    });

    const onSubmit = async (data: SignInFormData) => {
        try {
            const result = await signInWithEmail(data);
            if (result.success) {
                router.push(redirectTo);
                router.refresh();
                return;
            }
            if (result.twoFactorRequired) {
                setPendingCredentials({ email: data.email, password: data.password });
                setTwoFactorRequired(true);
                return;
            }
            toast.error(t('auth.signIn.failedTitle'), {
                description: result.error ?? t('auth.signIn.invalidCredentials'),
            });
        } catch (e) {
            toast.error(t('auth.signIn.failedTitle'), {
                description: e instanceof Error ? e.message : t('auth.signIn.unexpectedError')
            })
        }
    }

    const onVerifyTotp = async (totpCode: string) => {
        if (!pendingCredentials) return;
        setIsVerifying(true);
        try {
            const result = await verifyTwoFactorTotp({
                email: pendingCredentials.email,
                password: pendingCredentials.password,
                totpCode,
            });
            if (result.success) {
                router.push(redirectTo);
                router.refresh();
                return;
            }
            toast.error(t('auth.twoFactor.failedTitle'), {
                description: result.error ?? t('auth.twoFactor.invalidCode'),
            });
        } catch (e) {
            toast.error(t('auth.twoFactor.failedTitle'), {
                description: e instanceof Error ? e.message : t('auth.twoFactor.unexpectedError')
            })
        } finally {
            setIsVerifying(false);
        }
    }

    if (twoFactorRequired) {
        return (
            <React.Fragment key="two-factor">
                <h1 className="form-title">{t('auth.twoFactor.title')}</h1>
                <p className="text-sm text-gray-500 mb-6">
                    {t('auth.twoFactor.subtitle')}
                </p>

                <form onSubmit={handleSubmit((_data) => onVerifyTotp(getValues('totpCode') ?? ''))} className="space-y-5">
                                    <InputField
                                        name="totpCode"
                                        label={t('auth.twoFactor.codeLabel')}
                                        placeholder="000000"
                                        autoComplete="one-time-code"
                                        register={register}
                                        error={errors.totpCode}
                                        validation={{
                                            required: t('auth.twoFactor.codeRequired'),
                                            pattern: {
                                                value: /^\d{6}$/,
                                                message: t('auth.twoFactor.codeLength')
                                            }
                                        }}
                                    />

                    <Button type="submit" disabled={isVerifying} className="brand-btn w-full mt-5">
                        {isVerifying ? t('auth.twoFactor.verifying') : t('auth.twoFactor.submit')}
                    </Button>

                    <button
                        type="button"
                        className="w-full text-center text-sm text-gray-500 hover:text-gray-300"
                        onClick={() => {
                            setTwoFactorRequired(false);
                            setPendingCredentials(null);
                        }}
                    >
                        {t('auth.twoFactor.back')}
                    </button>
                </form>
            </React.Fragment>
        );
    }

    return (
        <React.Fragment key="credentials">
            <h1 className="form-title !mb-3">{t('auth.signIn.welcomeTitle')}</h1>
            <p className="mb-7 text-sm leading-6 text-gray-400">{t('auth.signIn.welcomeSubtitle')}</p>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
                <InputField
                    name="email"
                    label={t('auth.signIn.emailLabel')}
                    placeholder={t('auth.signIn.emailPlaceholder')}
                    register={register}
                    error={errors.email}
                    validation={emailFieldValidation}
                />

                <InputField
                    name="password"
                    label={t('auth.signIn.passwordLabel')}
                    placeholder={t('auth.signIn.passwordPlaceholder')}
                    type="password"
                    register={register}
                    error={errors.password}
                    validation={{ required: t('auth.signIn.passwordRequired'), minLength: { value: 8, message: t('auth.signIn.passwordMinLength') } }}
                />

                {passwordResetAvailable ? (
                    <div className="text-right">
                        <Link
                            className="text-sm text-gray-400 underline-offset-4 transition-colors hover:text-teal-300 hover:underline"
                            href="/forgot-password"
                        >
                            {t('auth.signIn.forgotLink')}
                        </Link>
                    </div>
                ) : null}

                <Button type="submit" disabled={isSubmitting} className="brand-btn w-full mt-5">
                    {isSubmitting ? t('auth.signIn.submitting') : t('auth.signIn.submit')}
                </Button>

                <FooterLink text={t('auth.signIn.noAccount')} linkText={publicSignUpOpen ? t('auth.signIn.createAccount') : t('auth.signIn.requestAccess')} href="/sign-up" />
            </form>
        </React.Fragment>
    );
};
export default SignInForm;
