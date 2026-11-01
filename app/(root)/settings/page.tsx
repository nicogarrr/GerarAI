import { getDcaAlertSettings } from '@/lib/actions/dca-settings.actions';
import { getT } from '@/lib/i18n/server';
import type { Metadata } from 'next';
import { getIBKRConnection } from '@/lib/actions/ibkr-settings.actions';
import SettingsContent from '@/components/settings/SettingsContent';
import { getLlmSettings, getLlmUsage } from '@/lib/actions/llm-settings.actions';
import { getPortfolioCurrencySettings } from '@/lib/actions/portfolio-settings.actions';
import { getTaxDeclarant } from '@/lib/actions/taxes.actions';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { redirectToSignIn } from '@/lib/auth/sign-in-redirect';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('settings.title') };
}

export default async function SettingsPage() {
  try {
    await requireAuthenticatedUser();
  } catch {
    return redirectToSignIn();
  }
  const [declarant, llm, llmUsage, currency, ibkr, dca] = await Promise.all([
    getTaxDeclarant().catch(() => null),
    getLlmSettings().catch(() => null),
    getLlmUsage().catch(() => null),
    getPortfolioCurrencySettings().catch(() => null),
    getIBKRConnection().catch(() => null),
    getDcaAlertSettings().catch(() => null),
  ]);

  return <SettingsContent declarant={declarant} llm={llm} llmUsage={llmUsage} currency={currency} ibkr={ibkr} dca={dca} />;
}
