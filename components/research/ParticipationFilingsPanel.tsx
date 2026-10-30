import { Panel } from '@/components/ui/panel';
import { participationNumber, participationSource, type ParticipationResponse } from '@/lib/research/schedule13dg';

export function ParticipationFilingsPanel({ data }: { data: ParticipationResponse | null }) {
  return <Panel title="Grandes accionistas (13D/G)">
    <p className="mb-3 text-sm text-gray-400">Declaraciones de participación ante la SEC, no operaciones de compra o venta. El declarante puede representar solo algunas entidades del grupo. La fecha de la posición no es la fecha de presentación.</p>
    {data === null ? <p className="text-sm text-gray-400">No se pudieron cargar las declaraciones ahora.</p> : data.filings.length === 0 ?
      <p className="text-sm text-gray-400">Sin declaraciones 13D/G sincronizadas. Esto no demuestra ausencia de grandes accionistas.</p> :
      <ul className="space-y-3">{data.filings.map(filing => {
        const source = participationSource(filing.source_url);
        return <li key={filing.accession_number} className="rounded-lg border border-gray-800 p-3 text-sm">
          <p className="font-medium text-gray-200">{filing.holder_name || 'Declarante N/D'} · {filing.form}</p>
          <p className="mt-1 text-gray-300">{participationNumber(filing.aggregate_shares)} acciones · {participationNumber(filing.percent_of_class, true)}</p>
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-400"><span>Posición a {filing.snapshot_date || 'N/D'}</span><span>Presentado {filing.filing_date || 'N/D'}</span></p>
          {filing.status !== 'parsed' ? <p className="mt-1 text-xs text-amber-300">Documento pendiente de lectura completa; los campos no verificados figuran como N/D.</p> : null}
          <p className="mt-1 text-xs text-gray-500">{filing.accession_number}{source ? <> · <a className="inline-flex min-h-11 items-center text-teal-300 underline" href={source} target="_blank" rel="noopener noreferrer">Documento SEC</a></> : ' · Fuente N/D'}</p>
        </li>;
      })}</ul>}
  </Panel>;
}
