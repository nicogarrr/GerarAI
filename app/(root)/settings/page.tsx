import { getDcaAlertSettings } from '@/lib/actions/dca-settings.actions';
import type { Metadata } from 'next';
import { getIBKRConnection } from '@/lib/actions/ibkr-settings.actions';
import SettingsContent from '@/components/settings/SettingsContent';
import { getLlmSettings } from '@/lib/actions/llm-settings.actions';
import { getPortfolioCurrencySettings } from '@/lib/actions/portfolio-settings.actions';
import { getTaxDeclarant } from '@/lib/actions/taxes.actions';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { redirectToSignIn } from '@/lib/auth/sign-in-redirect';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Ajustes' };

export default async function SettingsPage() {
  try {
    await requireAuthenticatedUser();
  } catch {
    return redirectToSignIn();
  }
  const [declarant, llm, currency, ibkr, dca] = await Promise.all([
    getTaxDeclarant().catch(() => null),
    getLlmSettings().catch(() => null),
    getPortfolioCurrencySettings().catch(() => null),
    getIBKRConnection().catch(() => null),
    getDcaAlertSettings().catch(() => null),
  ]);

  return <SettingsContent declarant={declarant} llm={llm} currency={currency} ibkr={ibkr} dca={dca} />;
}
