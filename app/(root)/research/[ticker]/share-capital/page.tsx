import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getShareCapital } from '@/lib/actions/share-capital.actions';
import { refreshCompanyFinancialsSEC } from '@/lib/actions/research.actions';
import { ShareCapitalPanel } from '@/components/research/ShareCapitalPanel';
import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Dilución y recompras',
  description: 'Saldos de acciones, emisiones y recompras con fuente verificable.',
};

export default async function ShareCapitalPage({ params }: { params: Promise<{ ticker: string }> }) {
  await requireAuthenticatedUser();
  const ticker = (await params).ticker.toUpperCase();
  const data = await getShareCapital(ticker).catch(() => null);
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-5xl flex-col gap-6">
    <PageHeader title={`Dilución y recompras · ${ticker}`} back={<Link className="inline-flex min-h-[44px] items-center text-teal-300 sm:min-h-0" href={`/research/${encodeURIComponent(ticker)}?view=financials`}>Volver a la empresa</Link>}
      actions={<MutationForm action={refreshCompanyFinancialsSEC.bind(null, ticker)} successMessage="Datos SEC actualizados"><Button type="submit">Actualizar SEC</Button></MutationForm>} />
    {data ? <ShareCapitalPanel data={data} /> : <p role="alert">No se pudieron cargar los datos. Vuelve a intentarlo.</p>}
  </main>;
}
