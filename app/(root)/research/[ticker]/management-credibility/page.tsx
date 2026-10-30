import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { ManagementCredibilitySection } from '@/components/research/sections/ManagementCredibilitySection';
import { getManagementCredibility } from '@/lib/actions/research-tools.actions';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Credibilidad de la directiva', description: 'Promesas fechadas de la directiva reconciliadas con los hechos financieros.' };

export default async function ManagementCredibilityPage({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  return <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-7xl flex-col gap-6"><PageHeader back={<Button asChild className="min-h-[44px] sm:min-h-0" size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft className="h-4 w-4" />Workspace de {ticker}</Link></Button>} description="Registra promesas fechadas y recóncilialas con los hechos financieros canónicos." kicker="Responsabilidad de la directiva" title="Credibilidad de la directiva" />
    <ManagementCredibilitySection dashboard={await getManagementCredibility(ticker)} ticker={ticker} />
  </main>;
}
