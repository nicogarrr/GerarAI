import SignInForm from '@/components/forms/SignInForm';
import { isPasswordResetEmailConfigured } from '@/lib/auth/email';
import { safeInternalPath } from '@/lib/auth/safe-redirect';

// `isPasswordResetEmailConfigured` lee SMTP del servidor: el formulario de
// cliente recibe el dato ya resuelto y no muestra un enlace de recuperación
// que este despliegue no puede atender.
export const dynamic = 'force-dynamic';

type Props = {
    searchParams: Promise<{ next?: string | string[] }>;
};

export default async function SignIn({ searchParams }: Props) {
    // `?next=` lo pone el middleware con la ruta pedida sin sesión. Se sanea
    // aquí (solo rutas internas) y el formulario vuelve a ella tras entrar.
    const { next } = await searchParams;
    return (
        <SignInForm
            passwordResetAvailable={isPasswordResetEmailConfigured()}
            redirectTo={safeInternalPath(next)}
        />
    );
}
