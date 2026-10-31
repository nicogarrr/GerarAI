'use client';

import Link from 'next/link';
import { Hourglass, MailX } from 'lucide-react';

import { useT } from '@/lib/i18n/client';
import type { PendingAccountState } from '@/lib/auth/pending-account';

type Props = {
    state: PendingAccountState;
    /** Volver al formulario (p. ej. "usar otra cuenta" tras un 403 en login). */
    onBack?: () => void;
};

/**
 * Aviso de cuenta pendiente o rechazada. Lo comparten la pagina
 * /cuenta-pendiente y los formularios de acceso (lo pintan en el hueco del
 * formulario, sin navegar, porque el layout de (auth) redirige a /inicio a
 * cualquiera con sesion y el estado debe verse siempre).
 */
const AccountStatusNotice = ({ state, onBack }: Props) => {
    const t = useT();
    const pending = state === 'pendiente';
    const Icon = pending ? Hourglass : MailX;
    return (
        <div className="flex flex-col">
            <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-amber-500/10">
                <Icon className="h-5 w-5 text-amber-300" aria-hidden="true" />
            </div>
            <h1 className="form-title !mb-3">
                {t(pending ? 'auth.pendingAccount.pendingTitle' : 'auth.pendingAccount.rejectedTitle')}
            </h1>
            <p className="text-sm text-gray-400">
                {t(pending ? 'auth.pendingAccount.pendingBody' : 'auth.pendingAccount.rejectedBody')}
            </p>
            {pending && (
                <p className="mt-3 text-sm text-gray-500">{t('auth.pendingAccount.pendingHint')}</p>
            )}
            <Link href="/sign-in" className="brand-btn mt-6 inline-block w-full text-center">
                {t('auth.pendingAccount.signInLink')}
            </Link>
            {onBack && (
                <button
                    type="button"
                    onClick={onBack}
                    className="mt-3 text-sm font-semibold text-gray-400 underline-offset-4 hover:underline"
                >
                    {t('auth.pendingAccount.backLink')}
                </button>
            )}
        </div>
    );
};

export default AccountStatusNotice;
