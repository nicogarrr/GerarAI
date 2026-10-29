import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatUserDateTime } from '@/lib/format';
import { changeHeadlineCopy } from '@/lib/research/change-copy';
import type { ResearchThesisChange } from '@/lib/actions/research.actions';

/**
 * Tarjeta de un cambio material (Seguir, WorldStocks punto 2): además del
 * resumen, dice si pide revisión y QUÉ toca (métricas y afirmaciones de la
 * tesis), usando solo campos persistidos por el motor. Sin esos campos no se
 * deduce nada: la línea no se pinta.
 */
export function ChangeImpactCard({ change, ticker, directionLabel, typeLabel }: {
  change: ResearchThesisChange;
  ticker: string;
  directionLabel: string;
  typeLabel: string;
}) {
  return (
    <div id={`thesis-change-${change.id}`} className="scroll-mt-24 rounded-lg border border-gray-800 p-4">
      <div className="flex flex-wrap gap-2">
        <Badge>{directionLabel}</Badge>
        <Badge variant="outline">{typeLabel}</Badge>
        <Badge variant="outline">materialidad {change.materiality_score}</Badge>
        {change.requires_review ? <Badge>revisión pendiente</Badge> : null}
      </div>
      <p className="mt-3 text-sm text-gray-300">{changeHeadlineCopy(change.summary).text}</p>
      {changeHeadlineCopy(change.summary).note ? <p className="mt-1 text-xs text-amber-300">{changeHeadlineCopy(change.summary).note}</p> : null}
      <p className="mt-2 text-xs text-gray-500">Registrado el {formatUserDateTime(change.created_at)} (Madrid)</p>
      {change.affected_metrics.length || change.affected_claim_ids.length ? (
        <p className="mt-2 text-xs text-gray-500">
          Toca:{' '}
          {[
            ...change.affected_metrics.map((metric) => metricLabel(metric)),
            ...(change.affected_claim_ids.length
              ? [`${change.affected_claim_ids.length} ${change.affected_claim_ids.length === 1 ? 'afirmación' : 'afirmaciones'} de la tesis`]
              : []),
          ].join(' · ')}
          {' · '}
          <Link className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={`/research/${encodeURIComponent(ticker)}?view=thesis`}>
            Ver la tesis
          </Link>
        </p>
      ) : null}
    </div>
  );
}
