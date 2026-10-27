import SignUpForm from '@/components/forms/SignUpForm';
import { resolveSignupPolicy, signUpPageMode } from '@/lib/auth/signup-policy';

// El formulario es un componente de cliente (react-hook-form) y necesita saber
// si el alta está abierta, pero `ALLOW_PUBLIC_SIGNUP` y `SIGNUP_ALLOWLIST` no
// son `NEXT_PUBLIC_*`: en el cliente siempre valdrían `undefined`. La página se
// queda como capa de servidor y le pasa el modo ya resuelto.
export const dynamic = 'force-dynamic';

type SignUpProps = { searchParams: Promise<{ invitacion?: string | string[] }> };

export default async function SignUp({ searchParams }: SignUpProps) {
    const params = await searchParams;
    const policy = resolveSignupPolicy(process.env);
    const mode = signUpPageMode(policy, params?.invitacion !== undefined);
    return (
        <SignUpForm
            signUpOpen={mode !== 'closed'}
            inviteOnly={mode === 'invite'}
            invitationsEnabled={policy.allowlist.size > 0}
        />
    );
}
