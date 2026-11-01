import { Metadata } from 'next';
import HelpTabs from '@/components/help/HelpTabs';
import { getT } from '@/lib/i18n/server';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return {
  title: t('landing.help.metaTitle'),
  description: t('landing.help.metaDescription'),
  // Página pública: el centro de ayuda se lee sin iniciar sesión, aunque los
  // módulos que documenta (research, cartera, ProPicks) sí exijan cuenta.
  robots: { index: true, follow: true },
  alternates: { canonical: '/help' },
  };
}

// Forzar renderizado dinámico
export const dynamic = 'force-dynamic';

export default function HelpPage() {
  return <HelpTabs />;
}
