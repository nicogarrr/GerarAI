import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { getT } from '@/lib/i18n/server';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return {
    title: t('auth.signUp.metaTitle'),
    description: t('auth.signUp.metaDescription'),
  };
}

export default function SignUpLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
