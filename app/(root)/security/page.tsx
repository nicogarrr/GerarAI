import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from "next/navigation";
import { requireAuthenticatedUser } from "@/lib/auth/require-user";
import { getTwoFactorStatus } from "@/lib/actions/auth.actions";
import { isPasswordResetEmailConfigured } from "@/lib/auth/email";
import TwoFactorSettings from "@/components/security/TwoFactorSettings";
import ChangePassword from "@/components/security/ChangePassword";
import PrivacySettings from "@/components/security/PrivacySettings";
import InstallApp from "@/components/pwa/InstallApp";
import { Panel } from "@/components/ui/panel";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = { title: 'Seguridad' };

export default async function SecurityPage() {
    let user;
    try {
        user = await requireAuthenticatedUser();
    } catch {
        redirect("/sign-in");
    }

    const status = await getTwoFactorStatus();
    const emailResetAvailable = isPasswordResetEmailConfigured();

    return (
        <main id="content" tabIndex={-1} className="space-y-8">
            <div>
                <h1 className="text-2xl font-bold text-white">Seguridad y privacidad</h1>
                <p className="text-sm text-gray-400 mt-1">
                    Ajustes de la cuenta de <span className="text-gray-200">{user.email}</span>.
                </p>
            </div>

            {status.success ? (
                <TwoFactorSettings initiallyEnabled={Boolean(status.enabled)} />
            ) : (
                <section
                    role="alert"
                    data-testid="two-factor-unavailable"
                    className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200"
                >
                    No se pudo comprobar el estado de la verificación en dos pasos (2FA). No
                    es lo mismo que tenerla desactivada: recarga la página o inténtalo más tarde.
                </section>
            )}

            <Panel title="Contraseña" description="Cambio autenticado sin depender del correo.">
                <div className="space-y-4">
                    <ChangePassword />
                    {emailResetAvailable ? (
                        <p className="text-sm text-gray-400">
                            ¿Has olvidado la contraseña? Cierra sesión y solicita un enlace en{' '}
                            <Link className="text-teal-300 hover:underline" href="/forgot-password">
                                restablecer contraseña
                            </Link>
                            .
                        </p>
                    ) : (
                        <p className="text-sm text-amber-200">
                            El restablecimiento por correo no está configurado en este
                            despliegue (falta SMTP). Usa el cambio autenticado de arriba o
                            contacta con soporte.
                        </p>
                    )}
                </div>
            </Panel>

            <Panel
                title="Datos y cuenta"
                description="Exporta una copia o elimina la cuenta y todos sus datos."
            >
                <PrivacySettings email={user.email ?? ''} />
            </Panel>

            <InstallApp />
        </main>
    );
}
