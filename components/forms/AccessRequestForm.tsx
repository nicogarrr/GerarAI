'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { requestAccess } from '@/lib/actions/access-request.actions';
import { ACCESS_REQUEST_LIMITS } from '@/lib/access-request';
import { useT } from '@/lib/i18n/client';

/**
 * Formulario "Pedir acceso" (registro cerrado). El campo `honeypot` va oculto a
 * las personas: si un bot lo rellena, el servidor responde bien y no guarda nada.
 */
export default function AccessRequestForm() {
    const t = useT();
    const [pending, setPending] = useState(false);
    const [done, setDone] = useState<string | null>(null);
    const [error, setError] = useState<{ message: string; field?: string } | null>(null);
    const [accepted, setAccepted] = useState(false);

    async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!accepted) {
            setError({ message: t('auth.accessRequest.termsRequired') });
            return;
        }
        const form = new FormData(event.currentTarget);
        setPending(true);
        setError(null);
        try {
            const result = await requestAccess({
                name: form.get('name'),
                email: form.get('email'),
                note: form.get('note'),
                honeypot: form.get('website'),
            });
            if (result.ok) setDone(result.message);
            else setError({ message: result.message, field: result.field });
        } catch {
            setError({ message: t('auth.accessRequest.sendError') });
        } finally {
            setPending(false);
        }
    }

    if (done) {
        return (
            <div role="status" className="rounded-lg border border-teal-900/60 bg-teal-950/20 p-4 text-sm leading-6 text-teal-100">
                {done}
            </div>
        );
    }

    return (
        <form onSubmit={onSubmit} className="space-y-5" aria-label={t('auth.accessRequest.ariaLabel')} noValidate>
            <div>
                <label htmlFor="ar-name" className="form-label mb-2 block">{t('auth.accessRequest.nameLabel')}</label>
                <input id="ar-name" name="name" required maxLength={ACCESS_REQUEST_LIMITS.nameMax} autoComplete="name" className="form-input block w-full" aria-invalid={error?.field === 'name'} />
            </div>
            <div>
                <label htmlFor="ar-email" className="form-label mb-2 block">{t('auth.accessRequest.emailLabel')}</label>
                <input id="ar-email" name="email" type="email" required maxLength={ACCESS_REQUEST_LIMITS.emailMax} autoComplete="email" className="form-input block w-full" aria-invalid={error?.field === 'email'} />
            </div>
            <div>
                <label htmlFor="ar-note" className="form-label mb-2 block">{t('auth.accessRequest.noteLabel')}</label>
                <textarea id="ar-note" name="note" rows={5} maxLength={ACCESS_REQUEST_LIMITS.noteMax} placeholder={t('auth.accessRequest.notePlaceholder')} className="form-input block min-h-36 overflow-y-auto w-full resize-y" aria-invalid={error?.field === 'note'} />
            </div>
            {/* Campo trampa: fuera de pantalla y fuera del orden de tabulacion. */}
            <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
                <label htmlFor="ar-website">{t('auth.accessRequest.honeypotLabel')}</label>
                <input id="ar-website" name="website" tabIndex={-1} autoComplete="off" />
            </div>
            {error ? <p role="alert" className="text-sm text-red-400">{error.message}</p> : null}
            <label className="flex items-start gap-2 text-sm leading-6 text-gray-300" htmlFor="ar-accept-terms">
                <input
                    id="ar-accept-terms"
                    type="checkbox"
                    className="mt-1 h-4 w-4 shrink-0 accent-teal-500"
                    checked={accepted}
                    onChange={(event) => setAccepted(event.target.checked)}
                />
                <span>
                    {t('auth.signUp.acceptTermsPrefix')}{' '}
                    <a className="text-teal-300 underline underline-offset-4 hover:text-teal-200" href="/terminos" target="_blank" rel="noreferrer">
                        {t('auth.signUp.termsLink')}
                    </a>{' '}
                    {t('auth.signUp.acceptTermsMiddle')}{' '}
                    <a className="text-teal-300 underline underline-offset-4 hover:text-teal-200" href="/privacidad" target="_blank" rel="noreferrer">
                        {t('auth.signUp.privacyLink')}
                    </a>
                    {t('auth.signUp.acceptTermsSuffix')}
                </span>
            </label>
            <Button type="submit" size="lg" disabled={pending || !accepted} className="w-full">
                {pending ? t('auth.accessRequest.submitting') : t('auth.accessRequest.submit')}
            </Button>
        </form>
    );
}
