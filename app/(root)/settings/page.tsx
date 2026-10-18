import { CheckCircle2, Cpu, Database, DollarSign, XCircle } from 'lucide-react';
import Link from 'next/link';
import { getResearchSettings } from '@/lib/actions/research.actions';
import { formatNumber, NA } from '@/lib/format';

import type { Metadata } from 'next';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = { title: 'Ajustes' };

const CONNECTOR_META: Record<string, { label: string; description: string }> = {
  edgar: { label: 'EDGAR', description: 'SEC EDGAR/XBRL — resultados, balance y ratios' },
  ibkr: { label: 'IBKR', description: 'Interactive Brokers Flex XML — posiciones de cartera en vivo' },
  fred: { label: 'FRED', description: 'FRED de la Reserva Federal — tipos macro, IPC, PIB' },
  manual_transcript_import: { label: 'Transcripts manuales', description: 'Importación de texto de transcripts independiente del proveedor' },
  langfuse: { label: 'Langfuse', description: 'Langfuse — observabilidad y trazas de LLM' },
  qdrant_url: { label: 'Qdrant', description: 'Qdrant — almacén vectorial para búsqueda RAG' },
};

const CONNECTOR_ORDER = ['ibkr', 'fred', 'manual_transcript_import', 'langfuse', 'qdrant_url'];

type ConnectorStatus = 'configured' | 'not_configured' | 'manual';

function connectorStatus(value: boolean | string): ConnectorStatus {
  if (value === true || (typeof value === 'string' && value.length > 0 && value !== 'false')) return 'configured';
  if (value === 'manual') return 'manual';
  return 'not_configured';
}

const CONNECTOR_STATUS_LABELS: Record<ConnectorStatus, string> = {
  configured: 'configurado',
  not_configured: 'sin configurar',
  manual: 'manual',
};

export default async function ResearchSettingsPage() {
  const settings = await getResearchSettings();

  const orderedConnectors = CONNECTOR_ORDER.map((key) => ({
    key,
    value: settings.connectors[key] ?? false,
  }));

  const extraConnectors = Object.entries(settings.connectors).filter(
    ([key]) => !CONNECTOR_ORDER.includes(key),
  );

  const allConnectors = [
    ...orderedConnectors,
    ...extraConnectors.map(([key, value]) => ({ key, value })),
  ];

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6">
      <header className="flex flex-col gap-4 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase text-teal-300">Configuración</p>
          <h1 className="mt-1 text-3xl font-bold text-gray-100">Ajustes y conectores</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Link className="rounded-lg border border-gray-800 px-3 py-2 text-teal-300 hover:border-gray-700" href="/alerts">Telegram y alertas</Link>
          <Link className="rounded-lg border border-gray-800 px-3 py-2 text-teal-300 hover:border-gray-700" href="/taxes">Impuestos</Link>
          <span className="rounded-lg border border-gray-800 bg-surface-1 px-4 py-2 text-gray-300">{settings.app_env}</span>
        </div>
      </header>

      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Database aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Conectores</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {allConnectors.map(({ key, value }) => {
            const meta = CONNECTOR_META[key];
            const status = connectorStatus(value);
            const statusBadge =
              status === 'configured'
                ? 'border-teal-800 bg-teal-950/30 text-teal-300'
                : status === 'manual'
                  ? 'border-amber-800 bg-amber-950/30 text-amber-300'
                  : 'border-gray-700 bg-gray-900 text-gray-500';

            return (
              <div key={key} className="rounded-md border border-gray-800 p-4">
                {/* F324: a 768px (grid de 2 columnas) la etiqueta larga del
                    conector empujaba el badge de estado fuera de la tarjeta;
                    min-w-0 deja encoger/envolver la etiqueta y shrink-0
                    protege el badge. */}
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    {status === 'configured' ? (
                      <CheckCircle2 aria-hidden="true" className="h-4 w-4 flex-shrink-0 text-teal-300" />
                    ) : (
                      <XCircle aria-hidden="true" className="h-4 w-4 flex-shrink-0 text-gray-500" />
                    )}
                    <span className="min-w-0 break-words font-semibold text-gray-200">{meta?.label ?? key}</span>
                  </div>
                  <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-semibold ${statusBadge}`}>
                    {CONNECTOR_STATUS_LABELS[status]}
                  </span>
                </div>
                <p className="mt-2 text-xs text-gray-500">{meta?.description ?? key}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="grid gap-6 md:grid-cols-2">
        <div className="rounded-lg border border-gray-800 bg-surface-1 p-5">
          <div className="mb-4 flex items-center gap-2">
            <DollarSign aria-hidden="true" className="h-5 w-5 text-teal-300" />
            <h2 className="text-lg font-semibold text-gray-100">Presupuesto</h2>
          </div>
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between rounded-md border border-gray-800 p-3">
              <span className="text-gray-400">Coste diario / tope</span>
              <span className="font-semibold text-gray-200">
                {formatNumber(settings.budget.daily_cost_eur, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} / {formatNumber(settings.budget.daily_cap_eur, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} EUR
              </span>
            </div>
            <div className="flex items-center justify-between rounded-md border border-gray-800 p-3">
              <span className="text-gray-400">Coste mensual / tope</span>
              <span className="font-semibold text-gray-200">
                {formatNumber(settings.budget.monthly_cost_eur, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} / {formatNumber(settings.budget.monthly_cap_eur, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} EUR
              </span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-gray-800 bg-surface-1 p-5">
          <div className="mb-4 flex items-center gap-2">
            <Cpu aria-hidden="true" className="h-5 w-5 text-teal-300" />
            <h2 className="text-lg font-semibold text-gray-100">Entorno de ejecución</h2>
          </div>
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between rounded-md border border-gray-800 p-3">
              <span className="text-gray-400">Entorno</span>
              <span className="font-semibold text-gray-200">{settings.app_env}</span>
            </div>
            <div className="flex items-center justify-between rounded-md border border-gray-800 p-3">
              <span className="text-gray-400">Versión MAF</span>
              <span className="font-mono font-semibold text-gray-200">{settings.maf_version}</span>
            </div>
            <div className="flex items-center justify-between rounded-md border border-gray-800 p-3">
              <span className="text-gray-400">Proveedor LLM</span>
              <span className="font-semibold text-gray-200">{settings.llm.provider}</span>
            </div>
            <div className="flex items-center justify-between rounded-md border border-gray-800 p-3">
              <span className="text-gray-400">Modelo LLM</span>
              <span className="font-mono font-semibold text-gray-200">{settings.llm.model ?? NA}</span>
            </div>
            <div className="flex items-center justify-between rounded-md border border-gray-800 p-3">
              <span className="text-gray-400">Estado LLM</span>
              <span
                className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                  settings.llm.configured
                    ? 'border-teal-800 bg-teal-950/30 text-teal-300'
                    : 'border-gray-700 bg-gray-900 text-gray-500'
                }`}
              >
                {settings.llm.configured ? 'configurado' : (settings.llm.reason ?? 'desactivado').replaceAll('_', ' ')}
              </span>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
