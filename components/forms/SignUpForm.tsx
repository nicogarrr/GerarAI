'use client';

import {useForm} from "react-hook-form";
import {Button} from "@/components/ui/button";
import InputField from "@/components/forms/InputField";
import SelectField from "@/components/forms/SelectField";
import {INVESTMENT_GOALS, INVESTMENT_GOAL_LABEL_KEYS, PREFERRED_INDUSTRIES, PREFERRED_INDUSTRY_LABEL_KEYS, RISK_TOLERANCE_OPTIONS, RISK_TOLERANCE_LABEL_KEYS} from "@/lib/constants";
import {useT} from "@/lib/i18n/client";
import {CountrySelectField} from "@/components/forms/CountrySelectField";
import FooterLink from "@/components/forms/FooterLink";
import {signUpWithEmail} from "@/lib/actions/auth.actions";
import {emailFieldValidation} from "@/lib/validation/email";
import AccessRequestForm from "@/components/forms/AccessRequestForm";
import AccountStatusNotice from "@/components/auth/AccountStatusNotice";
import {afterSignUpRoute, type PendingAccountState} from "@/lib/auth/pending-account";
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
    const t = useT();
    const router = useRouter()
    const [registeredState, setRegisteredState] = React.useState<PendingAccountState | null>(null);
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
                // Registro abierto con aprobacion: toda cuenta nueva nace
                // pendiente y sin sesion (autoSignIn=false), asi que /inicio
                // rebotaria a /sign-in. Solo un 'approved' explicito entra
                // directo; el resto ve la pantalla de cuenta pendiente.
                const route = afterSignUpRoute(result.accountStatus);
                if (route === '/inicio') {
                    router.push('/inicio');
                    return;
                }
                setRegisteredState(route);
                return;
            }
            toast.error(t('auth.signUp.failedTitle'), {
                description: result.error ?? t('auth.signUp.failedFallback'),
            });
        } catch (e) {
            toast.error(t('auth.signUp.failedTitle'), {
                description: e instanceof Error ? e.message : t('auth.signUp.unexpectedError')
            })
        }
    }

    // Alta completada: la pantalla de cuenta pendiente sustituye al
    // formulario (sin navegar: el layout de (auth) redirigiria a /inicio si
    // el despliegue aun crea sesion en el alta).
    if (registeredState) {
        return <AccountStatusNotice state={registeredState} />;
    }

    return (
        <>
            <h1 className="form-title !mb-3">{signUpOpen ? t('auth.signUp.titleOpen') : t('auth.signUp.titleClosed')}</h1>
            <p className="mb-7 text-sm leading-6 text-gray-400">
                {signUpOpen ? t('auth.signUp.subtitleOpen') : t('auth.signUp.subtitleClosed')}
            </p>

            {/* En producción el alta está cerrada por defecto (`disableSignUp`
                en `lib/better-auth/auth.ts`, que se abre con
                ALLOW_PUBLIC_SIGNUP=true). Se dice ANTES de rellenar el
                formulario en lugar de dejar que el usuario descubra el
                rechazo al enviarlo. */}
            {!signUpOpen ? (
                <div className="mb-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4">
                    <p className="text-sm font-semibold text-amber-200">{t('auth.signUp.closedTitle')}</p>
                    <p className="mt-1 text-sm leading-6 text-amber-100/90">
                        {t('auth.signUp.closedBody')}{' '}
                        <a href="/sign-in" className="underline underline-offset-4 hover:text-amber-100">
                            {t('auth.signUp.closedSignIn')}
                        </a>
                        .
                    </p>
                    {invitationsEnabled ? (
                        <p className="mt-2 text-sm leading-6 text-amber-100/90">
                            {t('auth.signUp.inviteBody')}{' '}
                            <a href="/sign-up?invitacion=1" className="underline underline-offset-4 hover:text-amber-100">
                                {t('auth.signUp.inviteLink')}
                            </a>
                            .
                        </p>
                    ) : null}
                </div>
            ) : null}

            {inviteOnly ? (
                <div className="mb-6 rounded-lg border border-teal-900/60 bg-teal-950/20 p-4">
                    <p className="text-sm font-semibold text-teal-200">{t('auth.signUp.inviteOnlyTitle')}</p>
                    <p className="mt-1 text-sm leading-6 text-teal-100/90">
                        {t('auth.signUp.inviteOnlyBody')}{' '}
                        <a href="/sign-up" className="underline underline-offset-4 hover:text-teal-100">
                            {t('auth.signUp.inviteOnlyLink')}
                        </a>
                        .
                    </p>
                </div>
            ) : null}

            {/* Registro cerrado: el formulario de alta se sustituye por la solicitud de acceso
                (el servidor rechazaria el alta de todos modos). */}
            {!signUpOpen ? <>
                <AccessRequestForm />
                <div className="mt-6"><FooterLink text={t('auth.signUp.haveAccount')} linkText={t('auth.signIn.submit')} href="/sign-in" /></div>
            </> : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
                <InputField
                    name="fullName"
                    label={t('auth.signUp.fullNameLabel')}
                    placeholder={t('auth.signUp.fullNamePlaceholder')}
                    register={register}
                    error={errors.fullName}
                    validation={{ required: t('auth.signUp.fullNameRequired'), minLength: { value: 2, message: t('auth.signUp.fullNameMinLength') } }}
                />

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
                    placeholder={t('auth.signUp.passwordPlaceholder')}
                    type="password"
                    autoComplete="new-password"
                    register={register}
                    error={errors.password}
                    validation={{ required: t('auth.signIn.passwordRequired'), minLength: { value: 8, message: t('auth.signIn.passwordMinLength') } }}
                />

                <CountrySelectField
                    name="country"
                    label={t('auth.signUp.countryLabel')}
                    control={control}
                    error={errors.country}
                    required
                />

                <SelectField
                    name="investmentGoals"
                    label={t('auth.signUp.goalsLabel')}
                    placeholder={t('auth.signUp.goalsPlaceholder')}
                    options={INVESTMENT_GOALS.map((o) => ({ value: o.value, label: t(INVESTMENT_GOAL_LABEL_KEYS[o.value]) }))}
                    control={control}
                    error={errors.investmentGoals}
                    required
                />

                <SelectField
                    name="riskTolerance"
                    label={t('auth.signUp.riskLabel')}
                    placeholder={t('auth.signUp.riskPlaceholder')}
                    options={RISK_TOLERANCE_OPTIONS.map((o) => ({ value: o.value, label: t(RISK_TOLERANCE_LABEL_KEYS[o.value]) }))}
                    control={control}
                    error={errors.riskTolerance}
                    required
                />

                <SelectField
                    name="preferredIndustry"
                    label={t('auth.signUp.industryLabel')}
                    placeholder={t('auth.signUp.industryPlaceholder')}
                    options={PREFERRED_INDUSTRIES.map((o) => ({ value: o.value, label: t(PREFERRED_INDUSTRY_LABEL_KEYS[o.value]) }))}
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
                                required: t('auth.signUp.acceptTermsRequired'),
                            })}
                        />
                        <span>
                            {t('auth.signUp.acceptTermsPrefix')}{' '}
                            <a
                                className="text-teal-300 underline underline-offset-4 hover:text-teal-200"
                                href="/terminos"
                                target="_blank"
                                rel="noreferrer"
                            >
                                {t('auth.signUp.termsLink')}
                            </a>{' '}
                            {t('auth.signUp.acceptTermsMiddle')}{' '}
                            <a
                                className="text-teal-300 underline underline-offset-4 hover:text-teal-200"
                                href="/privacidad"
                                target="_blank"
                                rel="noreferrer"
                            >
                                {t('auth.signUp.privacyLink')}
                            </a>
                            {t('auth.signUp.acceptTermsSuffix')}
                        </span>
                    </label>
                    {errors.acceptTerms ? (
                        <p id="acceptTerms-error" className="mt-2 text-sm text-red-400" role="alert">{errors.acceptTerms.message}</p>
                    ) : null}
                </div>

                <Button type="submit" disabled={isSubmitting || !signUpOpen} className="brand-btn w-full mt-5">
                    {isSubmitting ? t('auth.signUp.submitting') : signUpOpen ? t('auth.signUp.submitOpen') : t('auth.signUp.submitClosed')}
                </Button>

                <FooterLink text={t('auth.signUp.haveAccount')} linkText={t('auth.signIn.submit')} href="/sign-in" />
            </form>
            )}
        </>
    )
}
export default SignUpForm;
