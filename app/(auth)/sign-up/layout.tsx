import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { i18nPageMetadata } from '@/lib/i18n/metadata';

export async function generateMetadata(): Promise<Metadata> {
    return i18nPageMetadata('auth.signUp.metaTitle', 'auth.signUp.metaDescription');
}

export default function SignUpLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
