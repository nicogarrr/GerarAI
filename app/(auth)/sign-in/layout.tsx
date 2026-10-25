import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Iniciar sesión',
  description: 'Accede a tu espacio de investigación de GerarAI.',
};

export default function SignInLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
