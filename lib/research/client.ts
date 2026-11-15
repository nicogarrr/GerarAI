import {
  normalizeResearchBody,
  researchIdentityHeaders,
} from '@/lib/auth/research-identity';
import { AppError, ExternalAPIError } from '@/lib/types/errors';
import { researchErrorDetail, researchErrorFields } from '@/lib/research/error-detail';
import { researchRetryAfterSeconds } from '@/lib/research/rate-limit';

// Only pending network reads are coalesced, never settled response data.
const pendingReads = new Map<string, Promise<Response>>();

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
  let validationFields: string[] = [];
  try {
    const payload: unknown = await response.json();
    detail = researchErrorDetail(payload, detail);
    // Códigos pydantic crudos: el mensaje ya va traducido para la UI, así que
    // quien clasifique (ledgerRejection) no puede depender de él.
    validationFields = researchErrorFields(payload);
  } catch {
    // Preserve the HTTP status when the backend did not return JSON.
  }
  throw new AppError(detail, 'RESEARCH_API_ERROR', response.status, {
    path,
    ...(validationFields.length ? { validationFields } : {}),
    ...(response.status === 429 ? { retryAfterSeconds: researchRetryAfterSeconds(response.headers.get('Retry-After')) } : {}),
  });
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

  const doFetch = async () => {
    const headers = await buildHeaders();
    const fetchInit = {
      ...requestInit,
      body: normalized.body ?? undefined,
      headers,
      cache: requestInit.cache ?? 'no-store',
      signal: requestSignal(requestInit.signal, remainingMs()),
    };
    // Scope to the verified signed principal, language and every other stable
    // header. A fresh nonce/signature does not make an otherwise identical GET
    // distinct. Unknown/unsigned identities and caller-owned cancellation are
    // never shared. Writes are never shared, even when their body is identical.
    const tenant = headers.get('X-CavaAI-Tenant');
    const user = headers.get('X-CavaAI-User');
    const mayShare = method === 'GET' && tenant && user && !requestInit.signal
      && normalized.body == null
      && Object.keys(requestInit).every(key => ['method', 'headers', 'cache'].includes(key));
    if (!mayShare) return fetch(`${BACKEND_URL}${path}`, fetchInit);
    const volatile = new Set(['x-cavaai-nonce', 'x-cavaai-timestamp', 'x-cavaai-signature', 'x-cavaai-email-signature']);
    const stableHeaders = Array.from(headers.entries()).filter(([name]) => !volatile.has(name));
    const key = JSON.stringify([BACKEND_URL, method, path, timeoutMs, fetchInit.cache, stableHeaders]);
    let pending = pendingReads.get(key);
    if (!pending) {
      pending = fetch(`${BACKEND_URL}${path}`, fetchInit);
      pendingReads.set(key, pending);
      // Cleanup on both success and failure, without an unhandled finally()
      // rejection. No result survives the end of this pending network read.
      void pending.then(() => pendingReads.delete(key), () => pendingReads.delete(key));
    }
    // Response bodies are one-shot streams. Each caller gets its own clone.
    return (await pending).clone();
  };

  // Deadline compartido: el peor caso real (intento + espera 429 + reintento)
  // queda acotado por timeoutMs en lugar de multiplicarlo. Sin esta cota un
  // GET lento (~15s) seguido de 429 disparaba ~35s de función en Vercel y la
  // plataforma devolvía un 504 crudo antes de que la página pudiera degradar.
  const deadlineMs = Date.now() + timeoutMs;
  const remainingMs = () => Math.max(deadlineMs - Date.now(), 1);

  // Atribución de latencia por llamada al backend: UNA línea por request con
  // método, ruta, resultado y milisegundos totales (incluido el retry 429).
  // Motivo: atribuir los 4,6 s medidos de la pestaña Finanzas (5-nov-2026) a
  // sus endpoints concretos; la telemetría por workspace no llega a los logs.
  const startedAt = Date.now();
  const logCall = (outcome: string) => {
    console.info(`[research-api] ${method} ${path} ${outcome} ${Date.now() - startedAt}ms`);
  };

  let response: Response;
  try {
    response = await doFetch();
    // One retry at most, only after the FULL positive Retry-After. Missing,
    // invalid, zero and negative values use a safe 60s fallback. If the wait
    // does not fit the caller's existing deadline, surface 429 immediately.
    // Never turn a 60s lockout into repeated 5s retries.
    if (response.status === 429 && (method === 'GET' || method === 'HEAD')) {
      const raw = response.headers.get('Retry-After');
      const numeric = raw?.trim() ? Number(raw) : NaN;
      const seconds = Number.isFinite(numeric) ? numeric : raw ? (Date.parse(raw) - Date.now()) / 1000 : NaN;
      const waitMs = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds * 1000) : 60_000;
      const budgetLeftMs = deadlineMs - Date.now();
      if (budgetLeftMs > waitMs + 250) {
        // Release the rejected body's stream before waiting.
        void response.body?.cancel().catch(() => {});
        await new Promise((resolve) => setTimeout(resolve, waitMs));
        if (!requestInit.signal?.aborted && deadlineMs - Date.now() > 250) response = await doFetch();
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
    logCall(detail);
    throw new ExternalAPIError(
      `Research engine unavailable for ${path} (${detail}); reintenta en unos segundos.`,
      'research-engine',
      error,
    );
  }

  logCall(String(response.status));
  if (!response.ok) await responseError(response, path);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}
