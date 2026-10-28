import Link from 'next/link';
import { formatCountEs } from '@/lib/format';

import { Badge } from '@/components/ui/badge';
import { Panel } from '@/components/ui/panel';
import {
  holderChangeLabel,
  holdersLines,
  holdersTone,
  insiderLines,
  insiderTone,
  ownershipMoney,
  type OwnershipSignals,
  type OwnershipTone,
} from '@/lib/research/ownership-signals';

const TONE_CLASS: Record<OwnershipTone, string> = {
  positivo: 'border-teal-800 text-teal-300',
  negativo: 'border-red-900 text-red-300',
  neutro: 'border-gray-700 text-gray-300',
};

/**
 * Conexión 10b: insiders (Form 4) y fondos 13F del ticker, el mismo resumen
 * que lee la tesis (sección 24 del memo y hechos del narrador). Sin datos, se
 * dice por qué; nunca se pintan ceros como si fueran un dato.
 */
export function OwnershipSignalsPanel({ ticker, signals }: { ticker: string; signals: OwnershipSignals | null }) {
  const holdersHref = `/research/${encodeURIComponent(ticker)}?view=holders`;
  if (signals === null) {
    return (
      <Panel collapsible="mobile" title="Qué compran y venden directivos y grandes fondos">
        <p className="text-sm text-gray-400">No se pudo cargar el resumen de insiders y 13F ahora mismo.</p>
      </Panel>
    );
  }
  const { insider, holders } = signals;
  return (
    <Panel
      actions={<Link className="inline-flex min-h-[44px] sm:min-h-0 items-center text-sm text-teal-300" href={holdersHref}>Ver propietarios</Link>}
      collapsible="mobile"
      title="Qué compran y venden directivos y grandes fondos"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <section aria-label="Insiders (Form 4)">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-200">Compras y ventas de directivos (Form 4){insider.status === 'ok' ? ` · ${insider.window_days} días` : ''}</h3>
            {insider.status === 'ok' ? <Badge className={TONE_CLASS[insiderTone(insider)]} variant="outline">{insider.reading}</Badge> : null}
          </div>
          <ul className="space-y-1 text-sm text-gray-400">
            {insiderLines(insider).map((line) => <li key={line}>{line}</li>)}
          </ul>
        </section>
        <section aria-label="Fondos (13F)">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-200">Grandes fondos (informe 13F)</h3>
            {holders.status === 'ok' ? <Badge className={TONE_CLASS[holdersTone(holders)]} variant="outline">{formatCountEs(holders.holders_count, 'gestor', 'gestores')}</Badge> : null}
          </div>
          <ul className="space-y-1 text-sm text-gray-400">
            {holdersLines(holders).map((line) => <li key={line}>{line}</li>)}
          </ul>
          {holders.status === 'ok' && holders.top_holders.length ? (
            <ul className="mt-2 space-y-1 text-xs text-gray-500">
              {holders.top_holders.map((holder) => (
                <li key={holder.name}>
                  {holder.name}{holder.value_usd ? `: ${ownershipMoney(holder.value_usd)}` : ''} ({holderChangeLabel(holder.change)})
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>
      <p className="mt-3 text-xs text-gray-500">Fuente: SEC EDGAR (Form 4 y 13F), solo lo ya sincronizado. El 13F es trimestral, con hasta 45 días de retraso y solo posiciones largas. Este resumen entra en la tesis.</p>
    </Panel>
  );
}
