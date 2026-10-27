import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import BaseCurrencyForm from '@/components/settings/BaseCurrencyForm';
import LlmSettingsForm from '@/components/settings/LlmSettingsForm';
import TaxDeclarantForm from '@/components/settings/TaxDeclarantForm';
import { Panel } from '@/components/ui/panel';
import { getLlmSettings } from '@/lib/actions/llm-settings.actions';
import { getPortfolioCurrencySettings } from '@/lib/actions/portfolio-settings.actions';
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
  const [declarant, llm, currency] = await Promise.all([
    getTaxDeclarant().catch(() => null),
    getLlmSettings().catch(() => null),
    getPortfolioCurrencySettings().catch(() => null),
  ]);

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
      <Panel
        className="scroll-mt-24"
        description="Elige el proveedor y el modelo de IA de tu cuenta. Si usas tu propia API key, la llamada y su coste son tuyos."
        id="llm"
        title="Modelo de IA"
      >
        {llm ? (
          <LlmSettingsForm initial={llm} />
        ) : (
          <p className="text-sm text-gray-400">No disponible ahora. Recarga en unos segundos.</p>
        )}
      </Panel>
      <Panel
        className="scroll-mt-24"
        description="Divisa en la que ves la cartera y sus totales. La fiscalidad sigue en euros."
        id="divisa"
        title="Divisa base"
      >
        {currency ? (
          <BaseCurrencyForm initial={currency} />
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
