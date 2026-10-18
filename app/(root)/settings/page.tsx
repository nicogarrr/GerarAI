import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import TaxDeclarantForm from '@/components/settings/TaxDeclarantForm';
import { Panel } from '@/components/ui/panel';
import { getTaxDeclarant } from '@/lib/actions/taxes.actions';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Ajustes' };

export default async function SettingsPage() {
  try {
    await requireAuthenticatedUser();
  } catch {
    redirect('/sign-in');
  }
  const declarant = await getTaxDeclarant().catch(() => null);

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-5xl flex-col gap-6">
      <h1 className="text-3xl font-bold text-gray-100">Ajustes</h1>
      <Panel title="Datos fiscales del declarante">
        {declarant ? (
          <TaxDeclarantForm initial={declarant} />
        ) : (
          <p className="text-sm text-gray-400">No disponible ahora. Recarga en unos segundos.</p>
        )}
      </Panel>
      <Panel title="Telegram">
        <Link className="text-sm text-teal-300 hover:underline" href="/alerts">Conectar Telegram y gestionar alertas</Link>
      </Panel>
    </main>
  );
}
