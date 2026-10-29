import Link from 'next/link';
import { ChevronRight } from 'lucide-react';

import type { AnalystTargets } from '@/lib/research/analyst-targets';
import type { ResearchLongTermModel, MoatScoreMetric } from '@/lib/actions/research.actions';
import type { ShareCapital } from '@/lib/actions/share-capital.actions';
import type { ManagementCredibility } from '@/components/research/sections/ManagementCredibilitySection';
import { formatNumber, formatPrice, formatPercent } from '@/lib/format';

const GRADE_LABELS: Record<string, string> = {
  high: 'alta',
  mixed: 'mixta',
  low: 'baja',
  insufficient_history: 'historial insuficiente',
};

function Row({ href, label, value, note }: { href: string; label: string; value: string; note?: string }) {
  return (
    <li>
      <Link className="group flex min-h-[44px] items-center justify-between gap-3 border-b border-gray-800/70 py-2 last:border-0" href={href} scroll={false}>
        <span className="min-w-0">
          <span className="block text-xs text-gray-500">{label}</span>
          {note ? <span className="mt-0.5 block text-[11px] leading-4 text-gray-600">{note}</span> : null}
        </span>
        <span className="flex shrink-0 items-center gap-1 text-sm font-semibold text-gray-100 group-hover:text-teal-200">
          {value}
          <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 text-gray-600 group-hover:text-teal-300" />
        </span>
      </Link>
    </li>
  );
}

/**
 * Panel de vistazo rápido del Resumen (estilo Investing, decisión de Nico
 * del 29-oct-2026): solo datos reales y verificables que ya existen en la
 * ficha, cada fila enlazada a su sección. Sin veredicto técnico tipo
 * «venta fuerte» (descartado explícitamente). Una fila sin dato real no se
 * pinta: nada de relleno.
 */
export function QuickGlancePanel({ ticker, currency, model, analysts, livePrice, shareCapital, credibility, moatScore }: {
  ticker: string;
  currency: string | null | undefined;
  model: ResearchLongTermModel | null;
  analysts: AnalystTargets | null;
  livePrice: number | null;
  shareCapital: ShareCapital | null;
  credibility: ManagementCredibility | null;
  moatScore: MoatScoreMetric | null;
}) {
  const t = encodeURIComponent(ticker);
  const rows: React.ReactNode[] = [];

  // Valor del modelo propio: etiquetado como precio del modelo con su
  // periodo de datos, nunca como consenso de mercado (regla de la ficha).
  const baseValuation = model && model.status !== 'not_generated' && model.publishable
    ? model.scenarios?.base?.valuation?.value_per_share ?? null
    : null;
  if (baseValuation !== null && Number.isFinite(baseValuation)) {
    rows.push(
      <Row
        href={`/research/${t}?view=valoracion#modelo`}
        key="modelo"
        label={model?.as_of_period ? `Valor del modelo (datos a ${model.as_of_period})` : 'Valor del modelo'}
        value={currency ? formatPrice(baseValuation, currency) : formatNumber(baseValuation)}
      />,
    );
  }

  // Consenso de analistas (agregado de Yahoo, ya presente en la cabecera):
  // mediana y recorrido contra el precio en vivo de la cabecera.
  const median = analysts?.status === 'available' ? analysts.consensus?.median ?? null : null;
  if (median !== null && Number.isFinite(median)) {
    const recorrido = livePrice !== null && livePrice > 0 ? (median - livePrice) / livePrice : null;
    rows.push(
      <Row
        href="#analistas"
        key="analistas"
        label="Analistas (agregado Yahoo, no oficial)"
        note={recorrido !== null ? `Recorrido a la mediana: ${formatPercent(recorrido, { digits: 1, signDisplay: 'always' })}` : undefined}
        value={`Mediana ${analysts?.currency ? formatPrice(median, analysts.currency) : formatNumber(median)}`}
      />,
    );
  }

  // Ideas rápidas verificables: recompras declaradas (SEC), compromisos de
  // la directiva y calidad financiera (marco de foso).
  if (shareCapital && shareCapital.status === 'OFICIAL') {
    const ultimaRecompra = shareCapital.annual_flows
      .filter((flow) => flow.shares_repurchased || flow.common_stock_repurchased)
      .sort((a, b) => b.date.localeCompare(a.date))[0];
    rows.push(
      <Row
        href={`/research/${t}?view=finanzas#dilucion`}
        key="recompras"
        label="Recompras (registros SEC)"
        value={ultimaRecompra ? `Sí, en ${ultimaRecompra.date.slice(0, 4)}` : 'Sin recompras declaradas'}
      />,
    );
  }
  if (credibility) {
    const grade = GRADE_LABELS[credibility.grade] ?? credibility.grade;
    rows.push(
      <Row
        href={`/research/${t}?view=seguimiento#directiva`}
        key="directiva"
        label="Compromisos de la directiva"
        note={credibility.counts.open > 0 ? `${credibility.counts.open} abierta${credibility.counts.open === 1 ? '' : 's'} por comprobar` : undefined}
        value={`${formatPercent(credibility.score, { digits: 0 })} · ${grade}`}
      />,
    );
  }
  const moatTrace = moatScore?.calculation_trace as { score?: number } | undefined;
  if (typeof moatTrace?.score === 'number') {
    rows.push(
      <Row
        href={`/research/${t}?view=valoracion#foso`}
        key="foso"
        label="Calidad financiera (marco de foso)"
        value={`${formatNumber(moatTrace.score, { maximumFractionDigits: 0 })}/100`}
      />,
    );
  }

  if (!rows.length) return null;
  return (
    <aside aria-label="Vistazo rápido" className="h-fit rounded-xl border border-gray-800 bg-surface-1 p-4">
      <h2 className="text-sm font-semibold text-gray-200">Vistazo rápido</h2>
      <ul className="mt-1">{rows}</ul>
    </aside>
  );
}
