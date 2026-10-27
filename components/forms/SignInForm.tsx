'use client';

import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import InputField from '@/components/forms/InputField';
import FooterLink from '@/components/forms/FooterLink';
import AuthPitch from '@/components/forms/AuthPitch';
import {signInWithEmail, verifyTwoFactorTotp} from "@/lib/actions/auth.actions";
import {emailFieldValidation} from "@/lib/validation/email";
import {toast} from "sonner";
import {useRouter} from "next/navigation";
import Link from "next/link";
import React, {useState} from "react";

type Props = {
    /** Solo se muestra el enlace de recuperación si el despliegue puede enviar correo. */
    passwordResetAvailable: boolean;
};

const SignInForm = ({ passwordResetAvailable }: Props) => {
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
                router.push('/inicio');
                router.refresh();
                return;
            }
            if (result.twoFactorRequired) {
                setPendingCredentials({ email: data.email, password: data.password });
                setTwoFactorRequired(true);
                return;
            }
            toast.error('No se pudo iniciar sesión', {
                description: result.error ?? 'Email o contraseña no válidos.',
            });
        } catch (e) {
            toast.error('No se pudo iniciar sesión', {
                description: e instanceof Error ? e.message : 'Ha ocurrido un error inesperado. Inténtalo de nuevo.'
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
                router.push('/inicio');
                router.refresh();
                return;
            }
            toast.error('Verificación fallida', {
                description: result.error ?? 'Código de autenticación no válido.',
            });
        } catch (e) {
            toast.error('Verificación fallida', {
                description: e instanceof Error ? e.message : 'Ha ocurrido un error inesperado.'
            })
        } finally {
            setIsVerifying(false);
        }
    }

    if (twoFactorRequired) {
        return (
            <React.Fragment key="two-factor">
                <h1 className="form-title">Verificación en dos pasos</h1>
                <p className="text-sm text-gray-500 mb-6">
                    Introduce el código de 6 dígitos de tu app de autenticación para continuar.
                </p>

                <form onSubmit={handleSubmit((_data) => onVerifyTotp(getValues('totpCode') ?? ''))} className="space-y-5">
                                    <InputField
                                        name="totpCode"
                                        label="Código de autenticación"
                                        placeholder="000000"
                                        autoComplete="one-time-code"
                                        register={register}
                                        error={errors.totpCode}
                                        validation={{
                                            required: 'El código de autenticación es obligatorio',
                                            pattern: {
                                                value: /^\d{6}$/,
                                                message: 'El código debe tener 6 dígitos'
                                            }
                                        }}
                                    />

                    <Button type="submit" disabled={isVerifying} className="brand-btn w-full mt-5">
                        {isVerifying ? 'Verificando…' : 'Verificar y entrar'}
                    </Button>

                    <button
                        type="button"
                        className="w-full text-center text-sm text-gray-500 hover:text-gray-300"
                        onClick={() => {
                            setTwoFactorRequired(false);
                            setPendingCredentials(null);
                        }}
                    >
                        Volver a iniciar sesión
                    </button>
                </form>
            </React.Fragment>
        );
    }

    return (
        <React.Fragment key="credentials">
            <h1 className="form-title">Bienvenido de nuevo</h1>

            {/* Contexto de producto: qué es GerarAI y qué se obtiene al entrar.
                Va entre el H1 y el formulario, sin quitar el formulario.
                El margen de `.form-title` (mb-12) era para separar el título
                del formulario; con un bloque en medio sobra, así que el bloque
                lo sube con un margen negativo. */}
            <AuthPitch className="-mt-8 border-b border-gray-700/50 pb-8" />

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
                <InputField
                    name="email"
                    label="Email"
                    placeholder="email@ejemplo.com"
                    register={register}
                    error={errors.email}
                    validation={emailFieldValidation}
                />

                <InputField
                    name="password"
                    label="Contraseña"
                    placeholder="Introduce tu contraseña"
                    type="password"
                    register={register}
                    error={errors.password}
                    validation={{ required: 'La contraseña es obligatoria', minLength: { value: 8, message: 'La contraseña debe tener al menos 8 caracteres' } }}
                />

                {passwordResetAvailable ? (
                    <div className="text-right">
                        <Link
                            className="text-sm text-gray-400 underline-offset-4 transition-colors hover:text-teal-300 hover:underline"
                            href="/forgot-password"
                        >
                            ¿Has olvidado tu contraseña?
                        </Link>
                    </div>
                ) : null}

                <Button type="submit" disabled={isSubmitting} className="brand-btn w-full mt-5">
                    {isSubmitting ? 'Iniciando sesión…' : 'Iniciar sesión'}
                </Button>

                <FooterLink text="¿No tienes cuenta?" linkText="Crear cuenta" href="/sign-up" />
            </form>
        </React.Fragment>
    );
};
export default SignInForm;
