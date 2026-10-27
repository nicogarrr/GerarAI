import { Database, FileSearch, GitBranch, type LucideIcon } from 'lucide-react';
import { resolveSignupPolicy } from '@/lib/auth/signup-policy';

export type ProductModule = {
    icon: LucideIcon;
    title: string;
    description: string;
};

/**
 * Los tres modulos del producto, en UNA sola lista.
 *
 * Antes vivian duplicados dentro de `app/(auth)/layout.tsx`: la landing, la
 * pantalla de acceso y el panel de la derecha de auth.tenian cada uno su
 * propia copia, y cualquier retoque de copy se aplicaba a una de ellas. Ahora
 * los tres importan de aqui, asi que no pueden desincronizarse.
 */
export const productModules: ProductModule[] = [
    { icon: FileSearch, title: 'Evidencia', description: 'Cada hecho y afirmación conserva su fuente.' },
    { icon: Database, title: 'Modelo a largo plazo', description: 'Motores y supuestos adaptados a cada empresa.' },
    { icon: GitBranch, title: 'Expectativa frente a realidad', description: 'Cada resultado revisa su previsión.' },
];

/**
 * El flujo que resume el producto, usado como titular de la demo publica.
 * Vive aqui para que la landing y la pantalla de acceso digan lo mismo.
 */
export const productChain = 'Evidencia → Modelo → Tesis';

/**
 * Si el alta de cuentas esta abierta A CUALQUIERA.
 *
 * Usa la misma politica que `lib/better-auth/auth.ts`
 * (`lib/auth/signup-policy.ts`): cerrada en produccion salvo
 * ALLOW_PUBLIC_SIGNUP=true. Con solo SIGNUP_ALLOWLIST sigue "cerrada" para el
 * publico: la landing no invita a registrarse y /sign-up ofrece la solicitud
 * de acceso, con un enlace al alta para invitados.
 *
 * OJO: `ALLOW_PUBLIC_SIGNUP` no es `NEXT_PUBLIC_*`, asi que solo se puede
 * llamar desde un SERVER component. En cliente daria siempre `undefined`.
 * Si un cliente necesita el dato, que lo pase el layout como prop.
 */
export function isPublicSignUpOpen(): boolean {
    return resolveSignupPolicy(process.env).publicOpen;
}
