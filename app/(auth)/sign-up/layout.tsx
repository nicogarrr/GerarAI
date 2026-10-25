import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Crear cuenta',
  description: 'Solicita acceso a GerarAI y empieza a documentar tus tesis de inversión.',
};

export default function SignUpLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
