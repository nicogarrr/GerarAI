import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { i18nPageMetadata } from '@/lib/i18n/metadata';

export async function generateMetadata(): Promise<Metadata> {
    return i18nPageMetadata('auth.pendingAccount.metaTitle', 'auth.pendingAccount.metaDescription');
}

export default function CuentaPendienteLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
