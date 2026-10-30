import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { getT } from '@/lib/i18n/server';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return {
    title: t('auth.signIn.metaTitle'),
    description: t('auth.signIn.metaDescription'),
  };
}

export default function SignInLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
