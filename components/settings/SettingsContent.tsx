import { getT } from '@/lib/i18n/server';
import DcaAlertsForm from '@/components/settings/DcaAlertsForm';
import LanguageForm from '@/components/settings/LanguageForm';
import type { DcaAlertSettings } from '@/lib/actions/dca-settings.actions';
import Link from 'next/link';
import IBKRConnectionForm from '@/components/settings/IBKRConnectionForm';
import type { IBKRConnection } from '@/lib/actions/ibkr-settings.actions';
import SettingsSection from '@/components/settings/SettingsSection';
import BaseCurrencyForm from '@/components/settings/BaseCurrencyForm';
import LlmSettingsForm from '@/components/settings/LlmSettingsForm';
import TaxDeclarantForm from '@/components/settings/TaxDeclarantForm';
import { Panel } from '@/components/ui/panel';
import type { LlmSettings } from '@/lib/actions/llm-settings.actions';
import type { PortfolioCurrencySettings } from '@/lib/actions/portfolio-settings.actions';
import type { TaxDeclarant } from '@/lib/actions/taxes.actions';

export type SettingsContentProps = {
  dca?: DcaAlertSettings | null;
  declarant: TaxDeclarant | null;
  llm: LlmSettings | null;
  currency: PortfolioCurrencySettings | null;
  ibkr: IBKRConnection | null;
};

export default async function SettingsContent({ declarant, llm, currency, ibkr, dca }: SettingsContentProps) {
  const t = await getT();
  const unavailable = <p className="text-sm text-gray-400">{t('settings.unavailable')}</p>;
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-3xl flex-col gap-5">
      <h1 className="text-3xl font-bold text-gray-100">{t('settings.title')}</h1>
      <nav aria-label={t('settings.navAria')} className="flex flex-wrap gap-2 text-sm">
        {[
          ['idioma', t('settings.sections.language')], ['ibkr', t('settings.sections.ibkr')], ['divisa', t('settings.sections.currency')], ['telegram', t('settings.sections.telegram')], ['dca', t('settings.sections.dca')], ['llm', t('settings.sections.llm')], ['fiscal', t('settings.sections.tax')],
        ].map(([id, label]) => (
          <a className="flex min-h-11 items-center rounded-lg border border-gray-700 px-3 text-gray-300 transition hover:border-teal-500 hover:text-teal-300 focus-visible:outline-2 focus-visible:outline-teal-400" href={`#${id}`} key={id}>
            {label}
          </a>
        ))}
      </nav>
      <Panel className="scroll-mt-24" id="idioma" title={t('settings.language.title')} description={t('settings.language.description')}>
        <LanguageForm />
      </Panel>
      <Panel className="scroll-mt-24" id="ibkr" title={t('settings.ibkr.title')} description="">
        {ibkr ? <IBKRConnectionForm initial={ibkr} /> : unavailable}
      </Panel>
      <Panel
        className="scroll-mt-24"
        description={t('settings.currency.description')}
        id="divisa"
        title={t('settings.currency.title')}
      >
        {currency ? <BaseCurrencyForm initial={currency} /> : unavailable}
      </Panel>
      <Panel className="scroll-mt-24" id="telegram" title={t('settings.telegram.title')}>
        <p className="text-sm text-gray-400">{t('settings.telegram.body')}</p>
        <Link className="inline-flex min-h-11 items-center gap-2 text-sm text-teal-300 hover:underline" href="/alerts">
          {t('settings.telegram.link')} <span aria-hidden="true">→</span>
        </Link>
      </Panel>
      <Panel className="scroll-mt-24" id="dca" title={t('settings.dca.title')}>
        {dca ? <DcaAlertsForm initial={dca} /> : unavailable}
      </Panel>
      <SettingsSection
        description={llm?.source === 'tenant' ? t('settings.llm.descriptionTenant') : t('settings.llm.descriptionPlatform')}
        id="llm"
        title={t('settings.llm.title')}
      >
        {llm ? <LlmSettingsForm initial={llm} /> : unavailable}
      </SettingsSection>
      <SettingsSection
        description={t('settings.tax.description')}
        id="fiscal"
        title={t('settings.tax.title')}
      >
        {declarant ? <TaxDeclarantForm initial={declarant} /> : unavailable}
      </SettingsSection>
    </main>
  );
}
