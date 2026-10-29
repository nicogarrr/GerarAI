import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { DecisionLessonsSection } from '@/components/research/sections/DecisionLessonsSection';
import { getDecisionLessons } from '@/lib/actions/research-tools.actions';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Lecciones de decisiones', description: 'Desvíos de previsión convertidos en lecciones revisadas de cada empresa.' };

export default async function DecisionLessonsPage({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  return <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-7xl flex-col gap-6"><PageHeader back={<Button asChild className="min-h-[44px] sm:min-h-0" size="sm" variant="ghost"><Link href={`/research/${ticker}`}><ArrowLeft className="h-4 w-4" />Workspace de {ticker}</Link></Button>} description="Convierte los desvíos de previsión en lecciones revisadas sin dejar que las conclusiones generadas automáticamente se vuelvan canónicas en silencio." kicker="Aprendizaje de decisiones" title="Lecciones de decisiones" />
    <DecisionLessonsSection data={await getDecisionLessons(ticker)} ticker={ticker} />
  </main>;
}
