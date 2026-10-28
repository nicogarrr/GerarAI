import DcaAlertsForm from '@/components/settings/DcaAlertsForm';
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

function Unavailable() {
  return <p className="text-sm text-gray-400">No disponible ahora. Recarga para volver a intentarlo.</p>;
}

export default function SettingsContent({ declarant, llm, currency, ibkr, dca }: SettingsContentProps) {
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-3xl flex-col gap-5">
      <h1 className="text-3xl font-bold text-gray-100">Ajustes</h1>
      <nav aria-label="Secciones de ajustes" className="flex flex-wrap gap-2 text-sm">
        {[
          ['ibkr', 'IBKR'], ['divisa', 'Divisa'], ['telegram', 'Telegram'], ['dca', 'Avisos DCA'], ['llm', 'IA'], ['fiscal', 'Fiscalidad'],
        ].map(([id, label]) => (
          <a className="flex min-h-11 items-center rounded-lg border border-gray-700 px-3 text-gray-300 transition hover:border-teal-500 hover:text-teal-300 focus-visible:outline-2 focus-visible:outline-teal-400" href={`#${id}`} key={id}>
            {label}
          </a>
        ))}
      </nav>
      <Panel className="scroll-mt-24" id="ibkr" title="Conectar IBKR" description="">
        {ibkr ? <IBKRConnectionForm initial={ibkr} /> : <Unavailable />}
      </Panel>
      <Panel
        className="scroll-mt-24"
        description="Divisa en la que ves la cartera y sus totales. La fiscalidad sigue en euros."
        id="divisa"
        title="Divisa base"
      >
        {currency ? <BaseCurrencyForm initial={currency} /> : <Unavailable />}
      </Panel>
      <Panel className="scroll-mt-24" id="telegram" title="Telegram">
        <p className="text-sm text-gray-400">La vinculación de Telegram desde la app no está disponible todavía. En Alertas puedes consultar el estado del canal configurado en el servidor.</p>
        <Link className="inline-flex min-h-11 items-center gap-2 text-sm text-teal-300 hover:underline" href="/alerts">
          Ver estado de Telegram y gestionar alertas <span aria-hidden="true">→</span>
        </Link>
      </Panel>
      <Panel className="scroll-mt-24" id="dca" title="Avisos DCA">
        {dca ? <DcaAlertsForm initial={dca} /> : <Unavailable />}
      </Panel>
      <SettingsSection
        description={llm?.source === 'tenant' ? 'Configuración con tu clave API.' : 'Proveedor de GerarAI o tu propia clave API.'}
        id="llm"
        title="Modelo de IA"
      >
        {llm ? <LlmSettingsForm initial={llm} /> : <Unavailable />}
      </SettingsSection>
      <SettingsSection
        description="Datos del declarante y custodia para el Modelo 720."
        id="fiscal"
        title="Datos fiscales del declarante"
      >
        {declarant ? <TaxDeclarantForm initial={declarant} /> : <Unavailable />}
      </SettingsSection>
    </main>
  );
}
