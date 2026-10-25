import type { Metadata } from 'next';

import ForgotPasswordForm from '@/components/auth/ForgotPasswordForm';
import { isPasswordResetEmailConfigured } from '@/lib/auth/email';
import { SUPPORT_EMAIL } from '@/lib/config/brand';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
    title: 'Restablecer contraseña',
    description: 'Solicita un enlace para restablecer la contraseña de tu cuenta de GerarAI.',
    robots: { index: false, follow: false },
};

export default function ForgotPasswordPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-lg px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">Restablecer contraseña</h1>
            <p className="mt-2 text-sm text-gray-400">
                Si tu cuenta tiene un email asociado, te enviaremos un enlace de un solo uso.
                Por seguridad no confirmamos si un email está registrado.
            </p>
            <div className="mt-8">
                <ForgotPasswordForm
                    emailConfigured={isPasswordResetEmailConfigured()}
                    supportEmail={SUPPORT_EMAIL}
                />
            </div>
        </main>
    );
}
