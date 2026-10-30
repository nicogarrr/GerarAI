'use client';

import {useForm} from "react-hook-form";
import {Button} from "@/components/ui/button";
import InputField from "@/components/forms/InputField";
import SelectField from "@/components/forms/SelectField";
import {INVESTMENT_GOALS, PREFERRED_INDUSTRIES, RISK_TOLERANCE_OPTIONS} from "@/lib/constants";
import {CountrySelectField} from "@/components/forms/CountrySelectField";
import FooterLink from "@/components/forms/FooterLink";
import {signUpWithEmail} from "@/lib/actions/auth.actions";
import {emailFieldValidation} from "@/lib/validation/email";
import AccessRequestForm from "@/components/forms/AccessRequestForm";
import {useRouter} from "next/navigation";
import {toast} from "sonner";
import React from "react";

/**
 * Formulario de alta. Recibe `signUpOpen` desde el servidor porque
 * `ALLOW_PUBLIC_SIGNUP` no es `NEXT_PUBLIC_*`: leerlo en el cliente daría
 * siempre `undefined` y el aviso de registro cerrado nunca aparecería.
 * `inviteOnly`: alta solo para los emails invitados (SIGNUP_ALLOWLIST).
 * `invitationsEnabled`: con el registro cerrado, enlaza al alta para invitados.
 */
type SignUpFormProps = { signUpOpen: boolean; inviteOnly?: boolean; invitationsEnabled?: boolean };

const SignUpForm = ({ signUpOpen, inviteOnly = false, invitationsEnabled = false }: SignUpFormProps) => {
    const router = useRouter()
    const {
        register,
        handleSubmit,
        control,
        formState: { errors, isSubmitting },
    } = useForm<SignUpFormData>({
        defaultValues: {
            fullName: '',
            email: '',
            password: '',
            country: 'ES',
            investmentGoals: 'growth',
            riskTolerance: 'moderate',
            preferredIndustry: 'technology',
            acceptTerms: false,
        },
        mode: 'onBlur'
    }, );

    const onSubmit = async (data: SignUpFormData) => {
        try {
            const result = await signUpWithEmail(data);
            if (result.success) {
                router.push('/inicio');
                return;
            }
            toast.error('No se pudo crear la cuenta', {
                description: result.error ?? 'No hemos podido crear tu cuenta.',
            });
        } catch (e) {
            toast.error('No se pudo crear la cuenta', {
                description: e instanceof Error ? e.message : 'Ha ocurrido un error inesperado. Inténtalo de nuevo.'
            })
        }
    }

    return (
        <>
            <h1 className="form-title !mb-3">{signUpOpen ? 'Crea tu cuenta' : 'Pide acceso a GerarAI'}</h1>
            <p className="mb-7 text-sm leading-6 text-gray-400">
                {signUpOpen ? 'Tu espacio para analizar empresas y seguir tu cartera.' : 'Déjanos tu email para solicitar una invitación.'}
            </p>

            {/* En producción el alta está cerrada por defecto (`disableSignUp`
                en `lib/better-auth/auth.ts`, que se abre con
                ALLOW_PUBLIC_SIGNUP=true). Se dice ANTES de rellenar el
                formulario en lugar de dejar que el usuario descubra el
                rechazo al enviarlo. */}
            {!signUpOpen ? (
                <div className="mb-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4">
                    <p className="text-sm font-semibold text-amber-200">El registro está cerrado por ahora</p>
                    <p className="mt-1 text-sm leading-6 text-amber-100/90">
                        Estamos abriendo el acceso por tandas para poder acompañar el alta. Pide acceso aquí
                        abajo y te avisamos en cuanto haya plaza. Si ya tienes cuenta,{' '}
                        <a href="/sign-in" className="underline underline-offset-4 hover:text-amber-100">
                            inicia sesión
                        </a>
                        .
                    </p>
                    {invitationsEnabled ? (
                        <p className="mt-2 text-sm leading-6 text-amber-100/90">
                            ¿Te han invitado?{' '}
                            <a href="/sign-up?invitacion=1" className="underline underline-offset-4 hover:text-amber-100">
                                Crea tu cuenta con el email invitado
                            </a>
                            .
                        </p>
                    ) : null}
                </div>
            ) : null}

            {inviteOnly ? (
                <div className="mb-6 rounded-lg border border-teal-900/60 bg-teal-950/20 p-4">
                    <p className="text-sm font-semibold text-teal-200">Alta por invitación</p>
                    <p className="mt-1 text-sm leading-6 text-teal-100/90">
                        Usa el email con el que te invitaron. Si no está en la lista, puedes{' '}
                        <a href="/sign-up" className="underline underline-offset-4 hover:text-teal-100">
                            pedir acceso
                        </a>
                        .
                    </p>
                </div>
            ) : null}

            {/* Registro cerrado: el formulario de alta se sustituye por la solicitud de acceso
                (el servidor rechazaria el alta de todos modos). */}
            {!signUpOpen ? <>
                <AccessRequestForm />
                <div className="mt-6"><FooterLink text="¿Ya tienes cuenta?" linkText="Iniciar sesión" href="/sign-in" /></div>
            </> : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
                <InputField
                    name="fullName"
                    label="Nombre completo"
                    placeholder="Introduce tu nombre completo"
                    register={register}
                    error={errors.fullName}
                    validation={{ required: 'El nombre es obligatorio', minLength: { value: 2, message: 'El nombre debe tener al menos 2 caracteres' } }}
                />

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
                    placeholder="Crea una contraseña segura"
                    type="password"
                    autoComplete="new-password"
                    register={register}
                    error={errors.password}
                    validation={{ required: 'La contraseña es obligatoria', minLength: { value: 8, message: 'La contraseña debe tener al menos 8 caracteres' } }}
                />

                <CountrySelectField
                    name="country"
                    label="País"
                    control={control}
                    error={errors.country}
                    required
                />

                <SelectField
                    name="investmentGoals"
                    label="Objetivo de inversión"
                    placeholder="Selecciona tu objetivo"
                    options={INVESTMENT_GOALS}
                    control={control}
                    error={errors.investmentGoals}
                    required
                />

                <SelectField
                    name="riskTolerance"
                    label="Tolerancia al riesgo"
                    placeholder="Selecciona tu nivel de riesgo"
                    options={RISK_TOLERANCE_OPTIONS}
                    control={control}
                    error={errors.riskTolerance}
                    required
                />

                <SelectField
                    name="preferredIndustry"
                    label="Sector preferido"
                    placeholder="Selecciona tu sector preferido"
                    options={PREFERRED_INDUSTRIES}
                    control={control}
                    error={errors.preferredIndustry}
                    required
                />

                {/* Consentimiento obligatorio: sin aceptar los documentos
                    legales no se crea la cuenta. Los enlaces abren en otra
                    pestaña para no perder lo ya rellenado. */}
                <div>
                    <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2 text-sm leading-6 text-gray-300" htmlFor="acceptTerms">
                        <input
                            id="acceptTerms"
                            type="checkbox"
                            className="mt-0.5 size-5 shrink-0 accent-teal-500"
                            aria-invalid={!!errors.acceptTerms}
                            aria-describedby={errors.acceptTerms ? 'acceptTerms-error' : undefined}
                            {...register('acceptTerms', {
                                required: 'Debes aceptar los Términos de uso y la Política de privacidad para crear la cuenta',
                            })}
                        />
                        <span>
                            He leído y acepto los{' '}
                            <a
                                className="text-teal-300 underline underline-offset-4 hover:text-teal-200"
                                href="/terminos"
                                target="_blank"
                                rel="noreferrer"
                            >
                                Términos de uso
                            </a>{' '}
                            y la{' '}
                            <a
                                className="text-teal-300 underline underline-offset-4 hover:text-teal-200"
                                href="/privacidad"
                                target="_blank"
                                rel="noreferrer"
                            >
                                Política de privacidad
                            </a>
                            . Ambos documentos están en fase de borrador.
                        </span>
                    </label>
                    {errors.acceptTerms ? (
                        <p id="acceptTerms-error" className="mt-2 text-sm text-red-400" role="alert">{errors.acceptTerms.message}</p>
                    ) : null}
                </div>

                <Button type="submit" disabled={isSubmitting || !signUpOpen} className="brand-btn w-full mt-5">
                    {isSubmitting ? 'Creando cuenta…' : signUpOpen ? 'Crear cuenta' : 'Registro cerrado'}
                </Button>

                <FooterLink text="¿Ya tienes cuenta?" linkText="Iniciar sesión" href="/sign-in" />
            </form>
            )}
        </>
    )
}
export default SignUpForm;
