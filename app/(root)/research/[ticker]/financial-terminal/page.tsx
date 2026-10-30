import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { FinancialTerminalSection } from '@/components/research/sections/FinancialTerminalSection';
import { getFinancialTerminal } from '@/lib/actions/research-tools.actions';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Terminal financiero', description: 'Estados financieros por periodo, segmento y métrica con su procedencia.' };

export default async function FinancialTerminalPage({ params, searchParams }: { params: Promise<{ ticker: string }>; searchParams: Promise<{ metrics?: string; years?: string; periodicity?: string }> }) {
  const [{ ticker: rawTicker }, query] = await Promise.all([params, searchParams]);
  const ticker = rawTicker.toUpperCase();
  const years = Math.max(1, Math.min(20, Number(query.years) || 10));
  const periodicity = ['all', 'annual', 'quarterly'].includes(query.periodicity ?? '') ? query.periodicity! : 'annual';
  return <main id="content" tabIndex={-1} className="mx-auto flex min-w-0 w-full max-w-[1600px] flex-col gap-6"><PageHeader back={<Button asChild className="min-h-[44px] sm:min-h-0" size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Ficha de {ticker}</Link></Button>} description="Métricas reportadas, normalizadas y calculadas con definiciones, fórmulas, confianza y trazabilidad de la fuente." kicker="Financieros con fuentes" title="Terminal financiero" />
    <FinancialTerminalSection metrics={query.metrics} periodicity={periodicity} terminal={await getFinancialTerminal(ticker, { metrics: query.metrics, years, periodicity })} years={years} />
  </main>;
}
