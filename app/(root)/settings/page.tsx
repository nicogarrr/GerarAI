import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { getIBKRConnection } from '@/lib/actions/ibkr-settings.actions';
import SettingsContent from '@/components/settings/SettingsContent';
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
  const [declarant, llm, currency, ibkr] = await Promise.all([
    getTaxDeclarant().catch(() => null),
    getLlmSettings().catch(() => null),
    getPortfolioCurrencySettings().catch(() => null),
    getIBKRConnection().catch(() => null),
  ]);

  return <SettingsContent declarant={declarant} llm={llm} currency={currency} ibkr={ibkr} />;
}
