import Link from 'next/link';
import type { ReactNode } from 'react';

/** Aviso ámbar de los formularios de autenticación (recuperación sin SMTP,
 *  enlace de restablecimiento inválido): misma caja y tipografía. */
export function AuthFormNotice({ title, children }: { title: ReactNode; children: ReactNode }) {
    return (
        <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100">
            <p className="font-medium">{title}</p>
            <p className="mt-1">{children}</p>
        </div>
    );
}

/** Resultado de un formulario de autenticación: alerta roja si es error,
 *  status verde si es confirmación. */
export function AuthFormResult({ message, isError }: { message: string | null; isError: boolean }) {
    if (!message) return null;
    return (
        <p
            className={`text-sm ${isError ? 'text-red-300' : 'text-teal-200'}`}
            role={isError ? 'alert' : 'status'}
        >
            {message}
        </p>
    );
}

/** Pie discreto con enlace de regreso (los dos formularios de recuperación
 *  enlazan a /sign-in con la misma presentación). */
export function AuthFormFooterLink({ href, children }: { href: string; children: ReactNode }) {
    return (
        <p className="text-sm text-gray-500">
            <Link className="underline hover:text-teal-300" href={href}>{children}</Link>
        </p>
    );
}
