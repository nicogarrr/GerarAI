import SignInForm from '@/components/forms/SignInForm';
import { isPasswordResetEmailConfigured } from '@/lib/auth/email';

// `isPasswordResetEmailConfigured` lee SMTP del servidor: el formulario de
// cliente recibe el dato ya resuelto y no muestra un enlace de recuperación
// que este despliegue no puede atender.
export const dynamic = 'force-dynamic';

export default function SignIn() {
    return <SignInForm passwordResetAvailable={isPasswordResetEmailConfigured()} />;
}
