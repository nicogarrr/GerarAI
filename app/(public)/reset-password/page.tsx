import type { Metadata } from 'next';

import ResetPasswordForm from '@/components/auth/ResetPasswordForm';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
    title: 'Nueva contraseña',
    description: 'Elige una nueva contraseña para tu cuenta de GerarAI.',
    robots: { index: false, follow: false },
};

export default async function ResetPasswordPage({
    searchParams,
}: {
    searchParams: Promise<{ token?: string; error?: string }>;
}) {
    const params = await searchParams;
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-lg px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">Nueva contraseña</h1>
            <p className="mt-2 text-sm text-gray-400">
                El enlace caduca y solo se puede usar una vez. Al guardarla se cerrarán
                las sesiones abiertas.
            </p>
            <div className="mt-8">
                <ResetPasswordForm
                    linkError={Boolean(params.error)}
                    token={params.token ?? ''}
                />
            </div>
        </main>
    );
}
