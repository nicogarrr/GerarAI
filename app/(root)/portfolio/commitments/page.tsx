import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { commitmentsUiEnabled } from '@/lib/commitments-flag';
import { getPortfolioCommitments } from '@/lib/actions/research-tools.actions';
import SourceCoverage from '@/components/portfolio/SourceCoverage';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const FLAGS: Record<string, string> = { conditional: 'condicional', negation_present: 'contiene negación' };

const DATE_BASIS: Record<string, string> = {
  call_date: 'fecha de llamada indicada al registrar',
  user_entered: 'fecha introducida, no verificada',
  registered_at: 'fecha de alta, NO la de la llamada',
};

export default async function PortfolioCommitmentsPage() {
  if (!commitmentsUiEnabled()) {
    return (
      <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6">
        <PageHeader kicker="Seguimiento de la directiva" title="Compromisos de tu cartera y watchlist" description="Esta función está desactivada en este entorno todavía." />
        <EmptyState title="Seguimiento de compromisos no disponible" />
      </main>
    );
  }
  const data = await getPortfolioCommitments();
  const withItems = data.companies.filter((c) => c.counts.total > 0);
  const ambiguous = data.companies.filter((c) => c.company_identity_ambiguous);
  // Sin datos por ausencia REAL: ni compromisos ni identidad ambigua.
  const withoutData = data.companies.length - withItems.length - ambiguous.length;
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6">
      <PageHeader
        kicker="Seguimiento de la directiva"
        title="Compromisos de tu cartera y watchlist"
        description="Frases de la directiva en llamadas, con cita literal, fuente y fecha. Un candidato sugerido no es una promesa confirmada: nada se marca cumplido o fallido sin evidencia, y un plazo vencido sin prueba queda como no verificado."
      />
      <p className="text-xs text-gray-500">
        {data.held_count} en cartera · {data.watchlist_count} en watchlist · {withItems.length} con compromisos o candidatos registrados. Las empresas sin datos no tienen conclusión: no significa que la directiva no haya prometido nada.
      </p>
      <SourceCoverage />
      {!withItems.length ? <EmptyState title="Aún no hay compromisos ni candidatos para las empresas de tu cartera ni de tu watchlist." /> : null}
      {ambiguous.length ? (
        <p className="text-xs text-amber-300">
          {ambiguous.map((c) => c.ticker).join(', ')}: identidad ambigua, pendiente de revisar. No se muestran compromisos porque la empresa no está resuelta, no porque falten.
        </p>
      ) : null}
      {withoutData > 0 ? (
        <p className="text-xs text-gray-500">
          {withoutData} empresa(s) del seguimiento sin compromisos registrados todavía: no significa que no existan, solo que no hay datos.
        </p>
      ) : null}
      {withItems.map((company) => (
        <section className="rounded-xl border border-gray-800 bg-surface-1 p-5" key={company.ticker}>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold text-gray-100">{company.ticker}{company.name ? ` · ${company.name}` : ''}</h2>
            {company.in_portfolio ? <span className="rounded border border-gray-700 px-1.5 text-xs text-gray-400">Cartera</span> : null}
            {company.in_watchlist ? <span className="rounded border border-gray-700 px-1.5 text-xs text-gray-400">Watchlist</span> : null}
            <span className="text-xs text-gray-500">{company.counts.registered} registrados · {company.counts.candidate} sugeridos sin verificar</span>
            <Link className="ml-auto text-xs underline" href={`/research/${company.ticker}/management-credibility`}>Detalle</Link>
          </div>
          <ul className="mt-3 grid gap-3">
            {company.items.map((item) => (
              <li className="rounded-lg border border-gray-800 p-3 text-sm" key={item.id}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{item.status === 'candidate' ? 'sugerido, sin verificar' : item.legacy_heuristic_target ? 'veredicto no verificado' : item.status}</Badge>
                  {item.flags?.length ? <span className="text-xs text-amber-300">{item.flags.map((f) => FLAGS[f] ?? f).join(', ')}</span> : null}
                </div>
                <p className="mt-2 text-gray-100">{item.quote_literal ? `“${item.quote_literal}”` : item.promise}</p>
                <p className="mt-1 text-xs text-gray-400">
                  {item.speaker ?? 'hablante no registrado'}{item.speaker_role ? `, ${item.speaker_role}` : ''} · {item.call_date ? `${item.call_date} (${DATE_BASIS[item.date_basis ?? ''] ?? 'base no registrada'})` : 'fecha de llamada no registrada'}
                  {item.source_url ? <> · <a className="underline" href={item.source_url} rel="noopener noreferrer" target="_blank">fuente</a></> : null}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
