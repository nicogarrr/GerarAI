import type { Metadata } from 'next';

import ForgotPasswordForm from '@/components/auth/ForgotPasswordForm';
import { isPasswordResetEmailConfigured } from '@/lib/auth/email';
import { SUPPORT_EMAIL } from '@/lib/config/brand';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
    title: 'Restablecer contraseña',
    description: 'Consulta cómo recuperar el acceso a tu cuenta de GerarAI.',
    robots: { index: false, follow: false },
};

export default function ForgotPasswordPage() {
    const emailConfigured = isPasswordResetEmailConfigured();
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-lg px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">Restablecer contraseña</h1>
            {emailConfigured ? (
                <p className="mt-2 text-sm text-gray-400">
                    Si tu cuenta tiene un email asociado, te enviaremos un enlace de un solo uso.
                    Por seguridad no confirmamos si un email está registrado.
                </p>
            ) : (
                <p className="mt-2 text-sm text-gray-400">
                    Este despliegue no tiene configurado el correo saliente, así que no podemos
                    enviarte ningún enlace de restablecimiento. Si ya has iniciado sesión, cambia
                    la contraseña desde Seguridad; si no puedes entrar, usa el canal de soporte.
                </p>
            )}
            <div className="mt-8">
                <ForgotPasswordForm
                    emailConfigured={emailConfigured}
                    supportEmail={SUPPORT_EMAIL}
                />
            </div>
        </main>
    );
}
