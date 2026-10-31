import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { getT } from '@/lib/i18n/server';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return {
    title: t('auth.pendingAccount.metaTitle'),
    description: t('auth.pendingAccount.metaDescription'),
  };
}

export default function CuentaPendienteLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
