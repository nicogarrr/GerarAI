import {
  normalizeResearchBody,
  researchIdentityHeaders,
} from '@/lib/auth/research-identity';
import { AppError, ExternalAPIError } from '@/lib/types/errors';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

/**
 * Tiempos máximos para que una lectura lenta no deje una página esperando en
 * silencio. 15s cubre operaciones normales; las lecturas de home/portfolio
 * tienen un presupuesto más corto porque son datos de navegación.
 */
export const RESEARCH_TIMEOUTS = {
  GLOBAL_MS: 15_000,
  // 45s LLM + DB/guard/transport. Still below the 60s page budget.
  CHAT_MS: 55_000,
  GET_FAST_MS: 8_000,
  // El escaneo insider descarga hasta 20 Form 4 de EDGAR en secuencia: 8s
  // cortaba la lectura a mitad y la pagina mostraba "motor desconectado".
  // El backend ya degrada por filing, asi que este es el presupuesto real
  // para completar el escaneo, no un timeout infinito.
  INSIDER_SCAN_MS: 30_000,
} as const;

export type ResearchRequestInit = RequestInit & {
  /** Timeout explícito en milisegundos para esta llamada. */
  timeoutMs?: number;
  /** Fuerza el presupuesto corto de lectura (8s). */
  fast?: boolean;
};

export function researchTimeoutFor(
  path: string,
  method = 'GET',
  init: Pick<ResearchRequestInit, 'timeoutMs' | 'fast'> = {},
): number {
  if (Number.isFinite(init.timeoutMs) && (init.timeoutMs as number) > 0) {
    return Math.floor(init.timeoutMs as number);
  }
  if (path === '/api/chat' && method.toUpperCase() === 'POST') {
    return RESEARCH_TIMEOUTS.CHAT_MS;
  }
  // El escaneo live de EDGAR no cabe en el presupuesto "fast" de navegacion.
  if (method.toUpperCase() === 'GET' && path.startsWith('/api/insider/signals')) {
    return RESEARCH_TIMEOUTS.INSIDER_SCAN_MS;
  }
  const fastHomeOrPortfolioPath =
    path.startsWith('/api/portfolio/') ||
    path === '/api/portfolio/summary' ||
    path === '/api/portfolio/positions' ||
    path === '/api/watchlist' ||
    path === '/api/market/indices' ||
    path === '/api/market/movers';
  return method.toUpperCase() === 'GET' && (init.fast === true || fastHomeOrPortfolioPath)
    ? RESEARCH_TIMEOUTS.GET_FAST_MS
    : RESEARCH_TIMEOUTS.GLOBAL_MS;
}

export function requestSignal(external: AbortSignal | null | undefined, timeoutMs: number): AbortSignal {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  if (!external) return timeoutSignal;
  // Hay que respetar ambos límites: el del caller y el presupuesto de la app.
  if (typeof AbortSignal.any === 'function') {
    return AbortSignal.any([external, timeoutSignal]);
  }
  const controller = new AbortController();
  const abort = (source: AbortSignal) => () => controller.abort(source.reason);
  const onExternalAbort = abort(external);
  const onTimeoutAbort = abort(timeoutSignal);
  if (external.aborted) controller.abort(external.reason);
  else if (timeoutSignal.aborted) controller.abort(timeoutSignal.reason);
  else {
    external.addEventListener('abort', onExternalAbort, { once: true });
    timeoutSignal.addEventListener('abort', onTimeoutAbort, { once: true });
  }
  return controller.signal;
}

async function responseError(response: Response, path: string): Promise<never> {
  let detail = `${response.status} ${response.statusText}`.trim();
  try {
    const payload = await response.json() as { detail?: string; message?: string };
    detail = payload.detail ?? payload.message ?? detail;
  } catch {
    // Preserve the HTTP status when the backend did not return JSON.
  }
  throw new AppError(detail, 'RESEARCH_API_ERROR', response.status, { path });
}

export async function researchRequest<T>(
  path: string,
  init: ResearchRequestInit = {},
): Promise<T> {
  const { timeoutMs: _timeoutMs, fast: _fast, ...requestInit } = init;
  const method = (requestInit.method ?? 'GET').toUpperCase();
  const timeoutMs = researchTimeoutFor(path, method, init);
  const normalized = await normalizeResearchBody(requestInit.body ?? null);
  const buildHeaders = async () => {
    // La identidad firmada lleva nonce de un solo uso: cada intento (incluido
    // el retry tras un 429) necesita cabeceras nuevas.
    const identityHeaders = await researchIdentityHeaders({
      method,
      path,
      body: normalized.body ?? null,
    });
    const headers = new Headers(requestInit.headers);
    for (const [key, value] of Object.entries(identityHeaders)) headers.set(key, value);
    if (normalized.contentType && !headers.has('Content-Type')) {
      headers.set('Content-Type', normalized.contentType);
    } else if (requestInit.body && !(requestInit.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    return headers;
  };

  const doFetch = async () =>
    fetch(`${BACKEND_URL}${path}`, {
      ...requestInit,
      body: normalized.body ?? undefined,
      headers: await buildHeaders(),
      cache: requestInit.cache ?? 'no-store',
      // Sin timeout un backend colgado deja la página entera esperando.
      // El presupuesto es ÚNICO para toda la operación (retry 429 incluido):
      // cada intento recibe solo el tiempo que queda hasta el deadline.
      signal: requestSignal(requestInit.signal, remainingMs()),
    });

  // Deadline compartido: el peor caso real (intento + espera 429 + reintento)
  // queda acotado por timeoutMs en lugar de multiplicarlo. Sin esta cota un
  // GET lento (~15s) seguido de 429 disparaba ~35s de función en Vercel y la
  // plataforma devolvía un 504 crudo antes de que la página pudiera degradar.
  const deadlineMs = Date.now() + timeoutMs;
  const remainingMs = () => Math.max(deadlineMs - Date.now(), 1);

  let response: Response;
  try {
    response = await doFetch();
    // 429 = ráfaga legítima contra el rate-limit, no un fallo: un único
    // retry con backoff (Retry-After, máx 5s) en métodos idempotentes evita
    // la pantalla de error genérica por navegar rápido. La espera también
    // sale del mismo presupuesto: si no queda tiempo para esperar y aún
    // lanzar el reintento, se devuelve el 429 tal cual (error honesto, sin
    // gastar más cuota de función que timeoutMs).
    if (response.status === 429 && (method === 'GET' || method === 'HEAD')) {
      const retryAfter = Number(response.headers.get('Retry-After') ?? '1');
      const waitMs = Math.min(Number.isFinite(retryAfter) ? retryAfter : 1, 5) * 1000;
      const budgetLeftMs = deadlineMs - Date.now();
      if (budgetLeftMs > waitMs + 250) {
        await new Promise((resolve) => setTimeout(resolve, waitMs));
        response = await doFetch();
      }
    }
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === 'TimeoutError';
    const abortedByCaller = error instanceof DOMException && error.name === 'AbortError';
    const detail = timedOut
      ? `timeout de ${timeoutMs} ms`
      : abortedByCaller
        ? 'cancelado por el llamador'
        : 'fetch fallido';
    throw new ExternalAPIError(
      `Research engine unavailable for ${path} (${detail}); reintenta en unos segundos.`,
      'research-engine',
      error,
    );
  }

  if (!response.ok) await responseError(response, path);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}
