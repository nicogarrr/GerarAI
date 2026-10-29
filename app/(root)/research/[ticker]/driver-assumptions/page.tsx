import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { DriverAssumptionsSection } from '@/components/research/sections/DriverAssumptionsSection';
import { getDriverAssumptions } from '@/lib/actions/research-tools.actions';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Supuestos de drivers', description: 'Ajustes bear/base/bull versionados que reconstruyen el modelo de la empresa.' };

export default async function DriverAssumptionsPage({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  return <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-7xl flex-col gap-6"><PageHeader back={<Button asChild className="min-h-[44px] sm:min-h-0" size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Workspace de {ticker}</Link></Button>} description="Ajustes bear/base/bull editables. Cada cambio crea una nueva versión inmutable y reconstruye el modelo." kicker="Modelo operativo" title="Supuestos de drivers" />
    <DriverAssumptionsSection assumptions={await getDriverAssumptions(ticker)} ticker={ticker} />
  </main>;
}
