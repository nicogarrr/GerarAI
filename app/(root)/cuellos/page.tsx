import type { Metadata } from 'next';
import Link from 'next/link';
import { ExternalLink } from 'lucide-react';

import BackendOffline from '@/components/system/BackendOffline';
import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  getBottleneckDiscoveries,
  getBottlenecks,
  runBottleneckDiscovery,
  type DiscoveryView,
} from '@/lib/actions/bottlenecks.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { BOTTLENECK_TO_THEMES } from '@/lib/market/theme-bottleneck-map';
import { NA, formatUserDate } from '@/lib/format';

export const metadata: Metadata = {
  title: 'Cuellos de botella',
  description:
    'Escasez detectada en las fuentes guardadas y candidatos de empresas inferidos por el modelo, siempre etiquetados.',
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const PAGE_SIZE = 20;

type PageProps = { searchParams: Promise<{ pagina?: string | string[] }> };

function parsePage(raw: string | string[] | undefined): number {
  const value = Array.isArray(raw) ? raw[0] : raw;
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

function SignalCard({ signal, minSources }: { signal: Awaited<ReturnType<typeof getBottlenecks>>['signals'][number]; minSources: number }) {
  const detected = signal.status === 'detectado';
  return (
    <li className="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-100">{signal.theme}</h2>
        {detected ? (
          <span className="rounded bg-teal-400/15 px-1.5 py-0.5 text-[10px] font-bold uppercase text-teal-300">
            Detectado
          </span>
        ) : (
          <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] font-bold uppercase text-gray-500">
            {NA}
          </span>
        )}
      </div>
      <p className="mt-3 text-xs text-gray-400">
        {detected
          ? `${signal.n_sources} fuentes independientes · última señal ${formatUserDate(signal.last_seen)}`
          : /* Puede haber evidencias enlazables y aun asi N/D: el umbral cuenta
               FUENTES independientes, no evidencias (Tester 6: 2 evidencias de
               un mismo editor no detectan). El contador lo hace visible. */
            `${signal.n_sources} de ${minSources} fuentes independientes · sin evidencia suficiente`}
      </p>
      {signal.evidence?.length ? (
        <details className="mt-3 text-xs">
          <summary className="min-h-11 cursor-pointer py-3 text-teal-300">Ver evidencias guardadas ({signal.evidence.length})</summary>
          <ul className="mt-2 space-y-2">
            {signal.evidence.map((item) => (
              <li key={item.id}>
                {item.status === 'verificada' && item.url ? (
                  <a className="inline-flex min-h-11 items-center break-words text-teal-300 underline" href={item.url} rel="noopener noreferrer" target="_blank">
                    {item.title ?? item.url}
                  </a>
                ) : <span className="text-gray-500">{item.title ?? 'Evidencia no disponible'} · sin enlace verificable</span>}
              </li>
            ))}
          </ul>
        </details>
      ) : detected ? <p className="mt-2 text-xs text-gray-500">Evidencias guardadas no disponibles para consultar.</p> : null}
      {BOTTLENECK_TO_THEMES[signal.theme]?.length ? (
        <p className="mt-3 border-t border-gray-800 pt-2 text-xs text-gray-400">
          Temas relacionados:{' '}
          <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300 underline hover:text-teal-200" href="/temas">
            {BOTTLENECK_TO_THEMES[signal.theme].map((theme) => theme.name).join(' · ')}
          </Link>
        </p>
      ) : null}
    </li>
  );
}

function DiscoveryCard({ item }: { item: DiscoveryView }) {
  const known = item.ticker !== NA;
  return (
    <li className="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {known ? (
          <Link
            className="inline-flex min-h-11 min-w-11 items-center text-base font-semibold text-teal-300 hover:text-teal-200"
            href={`/research/${item.ticker}`}
          >
            {item.ticker}
          </Link>
        ) : (
          <span className="text-base font-semibold text-gray-300">Sin identificar</span>
        )}
        <span className="text-xs text-gray-500">{item.theme}</span>
        <Badge className="border-amber-500/50 text-amber-300" variant="outline">
          {item.label}
        </Badge>
        {!item.theme_detected ? (
          <Badge className="border-gray-600 text-gray-400" variant="outline">
            Tema ya no detectado
          </Badge>
        ) : null}
        {item.in_portfolio ? (
          <Badge className="border-teal-500/50 text-teal-300" variant="outline">
            En tu cartera
          </Badge>
        ) : null}
        {item.in_watchlist ? (
          <Badge className="border-sky-500/50 text-sky-300" variant="outline">
            En tu lista de seguimiento
          </Badge>
        ) : null}
        {item.recent_insider_activity ? (
          <Badge className="border-violet-500/50 text-violet-300" variant="outline">
            Actividad insider reciente
          </Badge>
        ) : null}
      </div>
      <p className="mt-2 text-sm leading-relaxed text-gray-300">{item.reasoning}</p>
      {item.evidence.length > 0 ? (
        <ul className="mt-3 space-y-1 border-t border-gray-800 pt-2">
          {item.evidence.map((evidence) => (
            <li className="flex items-center gap-1.5 text-xs" key={evidence.id}>
              {evidence.status === 'verificada' && evidence.url ? (
                <a
                  className="inline-flex min-h-11 items-center gap-1 text-teal-300 underline hover:text-teal-200"
                  href={evidence.url}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  {evidence.title ?? evidence.url}
                  <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
              ) : (
                <span className="text-gray-500">
                  {evidence.title ?? 'Evidencia'} · {NA}
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-3 text-[11px] text-gray-500">
        {formatUserDate(item.created_at)} · modelo {item.model} · última señal del tema:{' '}
        {item.theme_last_seen ? formatUserDate(item.theme_last_seen) : NA}
      </p>
    </li>
  );
}

export default async function CuellosPage({ searchParams }: PageProps) {
  const page = parsePage((await searchParams).pagina);
  let bottlenecks: Awaited<ReturnType<typeof getBottlenecks>>;
  let discoveries: Awaited<ReturnType<typeof getBottleneckDiscoveries>>;
  try {
    [bottlenecks, discoveries] = await Promise.all([
      getBottlenecks(),
      getBottleneckDiscoveries((page - 1) * PAGE_SIZE, PAGE_SIZE),
    ]);
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature="Cuellos de botella" retryHref="/cuellos" />;
    }
    throw error;
  }

  const detectedCount = bottlenecks.signals.filter((signal) => signal.status === 'detectado').length;
  const totalPages = Math.max(1, Math.ceil(discoveries.total / PAGE_SIZE));
  const pageHref = (target: number) => (target <= 1 ? '/cuellos' : `/cuellos?pagina=${target}`);

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
      <header>
        <h1 className="text-3xl font-bold text-gray-100">Cuellos de botella</h1>
        <p className="mt-1 text-sm text-gray-400">
          {detectedCount} de {bottlenecks.signals.length} temas con escasez detectada
        </p>
      </header>

      <section aria-label="Señales de escasez">
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {bottlenecks.signals.map((signal) => (
            <SignalCard key={signal.theme} signal={signal} minSources={bottlenecks.min_sources} />
          ))}
        </ul>
      </section>

      <section aria-label="Candidatos inferidos">
        <h2 className="mb-3 text-xl font-semibold text-gray-100">Candidatos inferidos</h2>
        <MutationForm action={runBottleneckDiscovery} showSuccessInline className="mb-3">
          <Button type="submit" variant="outline">Buscar candidatos inferidos</Button>
          <p className="mt-2 text-sm text-gray-400">Solo evidencias guardadas y modelos gratuitos. Las hipótesis no son hechos ni recomendaciones.</p>
        </MutationForm>
        {discoveries.items.length === 0 && discoveries.total === 0 ? (
          <div className="rounded-xl border border-gray-800 bg-surface-1 p-5">
            <p className="font-semibold text-gray-100">Sin candidatos todavía</p>
            <p className="mt-1 text-sm text-gray-400">
              No hay candidatos guardados. Puedes solicitar un barrido; si no hay evidencias suficientes o el modelo gratuito no está disponible, no se inventan resultados.
            </p>
          </div>
        ) : discoveries.items.length === 0 ? (
          <div className="rounded-xl border border-gray-800 bg-surface-1 p-5">
            <p className="font-semibold text-gray-100">Página fuera de rango</p>
            <p className="mt-1 text-sm text-gray-400">
              Hay {discoveries.total} candidatos en {totalPages}{' '}
              {totalPages === 1 ? 'página' : 'páginas'}; esta página no existe.
            </p>
            <nav aria-label="Volver al listado" className="mt-3 flex flex-wrap gap-2 text-sm">
              <Link
                className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-teal-300 hover:bg-gray-800"
                href="/cuellos"
              >
                Primera página
              </Link>
              {totalPages > 1 ? (
                <Link
                  className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-teal-300 hover:bg-gray-800"
                  href={pageHref(totalPages)}
                >
                  Última página
                </Link>
              ) : null}
            </nav>
          </div>
        ) : (
          <>
            <ul className="grid gap-3 sm:grid-cols-2">
              {discoveries.items.map((item) => (
                <DiscoveryCard item={item} key={item.id} />
              ))}
            </ul>
            <nav aria-label="Paginar candidatos" className="mt-4 flex items-center gap-2 text-sm">
              {page > 1 ? (
                <Link
                  className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                  href={pageHref(page - 1)}
                >
                  Anterior
                </Link>
              ) : null}
              <span className="px-2 text-gray-500">Página {page}</span>
              {discoveries.has_more ? (
                <Link
                  className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                  href={pageHref(page + 1)}
                >
                  Siguiente
                </Link>
              ) : null}
            </nav>
          </>
        )}
      </section>

      <footer className="border-t border-gray-800 pt-3 text-xs text-gray-500">
        <p>{bottlenecks.method} · {bottlenecks.limitation}</p>
        <p className="mt-1">{discoveries.note}</p>
      </footer>
    </main>
  );
}
