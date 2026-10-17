/**
 * Tipos centralizados para manejo de errores
 * Reemplaza el uso de 'any' en catch blocks
 */

/**
 * Error base de la aplicación
 */
export class AppError extends Error {
  public readonly code: string;
  public readonly statusCode: number;
  public readonly cause: unknown;
  constructor(message: string, code: string, statusCode: number = 500, cause?: unknown) {
    super(message);
    this.name = 'AppError';
    this.code = code;
    this.statusCode = statusCode;
    this.cause = cause;
  }
}

/**
 * Error de validación
 */
export class ValidationError extends AppError {
  public readonly field: string | undefined;
  constructor(message: string, field?: string) {
    super(message, 'VALIDATION_ERROR', 400);
    this.name = 'ValidationError';
    this.field = field;
  }
}

/**
 * Error de autenticación
 */
export class AuthenticationError extends AppError {
  constructor(message: string = 'Authentication failed') {
    super(message, 'AUTH_ERROR', 401);
    this.name = 'AuthenticationError';
  }
}

/**
 * Error de autorización
 */
export class AuthorizationError extends AppError {
  constructor(message: string = 'Access denied') {
    super(message, 'AUTHORIZATION_ERROR', 403);
    this.name = 'AuthorizationError';
  }
}

/**
 * Error de recurso no encontrado
 */
export class NotFoundError extends AppError {
  constructor(resource: string = 'Resource') {
    super(`${resource} not found`, 'NOT_FOUND', 404);
    this.name = 'NotFoundError';
  }
}

/**
 * Error de rate limit
 */
export class RateLimitError extends AppError {
  constructor(message: string = 'Rate limit exceeded') {
    super(message, 'RATE_LIMIT_ERROR', 429);
    this.name = 'RateLimitError';
  }
}

/**
 * Error de API externa
 */
export class ExternalAPIError extends AppError {
  public readonly service: string;
  public readonly originalError: unknown;
  constructor(message: string, service: string, originalError?: unknown) {
    super(message, 'EXTERNAL_API_ERROR', 502, originalError);
    this.name = 'ExternalAPIError';
    this.service = service;
    this.originalError = originalError;
  }
}

/**
 * Error de base de datos
 */
export class DatabaseError extends AppError {
  constructor(message: string, cause?: unknown) {
    super(message, 'DATABASE_ERROR', 500, cause);
    this.name = 'DatabaseError';
  }
}

/**
 * Error de recurso duplicado (watchlist, alertas, colecciones...)
 */
export class DuplicateError extends AppError {
  public readonly resource: string | undefined;
  constructor(message: string = 'Este elemento ya existe', resource?: string) {
    super(message, 'DUPLICATE_ERROR', 409);
    this.name = 'DuplicateError';
    this.resource = resource;
  }
}

/**
 * Type guard para verificar si un error es de tipo AppError
 */
export function isAppError(error: unknown): error is AppError {
  return error instanceof AppError;
}

/**
 * 401/403: sesión caducada o acceso denegado. NUNCA es «sin datos»: una
 * página que lo traduce a su estado vacío le dice al usuario «no tienes
 * nada» cuando en realidad no se le dejó entrar. Se propaga o se redirige.
 */
export function isAuthError(error: unknown): boolean {
  return isAppError(error) && (error.statusCode === 401 || error.statusCode === 403);
}

/**
 * Type guard para verificar si un error es un Error estándar
 */
export function isError(error: unknown): error is Error {
  return error instanceof Error;
}

/**
 * Convierte un error desconocido a un AppError
 */
export function toAppError(error: unknown, defaultMessage: string = 'An unexpected error occurred'): AppError {
  if (isAppError(error)) {
    return error;
  }
  
  if (isError(error)) {
    return new AppError(error.message, 'UNKNOWN_ERROR', 500, error);
  }
  
  return new AppError(defaultMessage, 'UNKNOWN_ERROR', 500, error);
}

/**
 * Extrae mensaje de error de forma segura
 */
export function getErrorMessage(error: unknown): string {
  if (isAppError(error) || isError(error)) {
    return error.message;
  }
  
  if (typeof error === 'string') {
    return error;
  }
  
  return 'An unknown error occurred';
}


/**
 * Next.js enmascara en producción los errores de Server Actions y Server
 * Components con un mensaje genérico + digest ("An error occurred in the
 * Server Components render…"). Mostrar ese texto crudo en un toast no ayuda:
 * lo traducimos a un mensaje accionable de "motor no disponible, reintenta".
 * Los errores de negocio reales (AppError serializado, validaciones) se
 * devuelven traducidos pero con su causa intacta.
 */
const NEXT_PROD_GENERIC_MARKERS = [
  'server components render',
  'server action',
  'unexpected response',
  'digest',
];

/** Causa accionable de un error, para decidir el toast (reintentar, info...) */
export type ErrorCause = 'offline' | 'stale' | 'duplicate' | 'validation' | 'auth' | 'not_found' | 'unknown';

/**
 * Un despliegue nuevo deja el cliente con chunks o Server Actions viejas:
 * se detecta ANTES que los genéricos `offline` porque los mensajes
 * ("failed to find server action…", "loading chunk…") también contienen
 * palabras genéricas como "server action" o "failed".
 */
const STALE_MARKERS = [
  'failed to find server action',
  'action could not be found',
  'loading chunk',
  'chunkloaderror',
  'revision mismatch',
  'stale',
];

const OFFLINE_MARKERS = [
  'fetch failed',
  'failed to fetch',
  'networkerror',
  'network error',
  'load failed',
  'econnrefused',
  'etimedout',
  'econnreset',
  'enotfound',
  'socket hang up',
  'no responde',
  'motor de análisis no',
  'backend no configurado',
];

const DUPLICATE_MARKERS = [
  'already exists',
  'already following',
  'duplicate',
  'already added',
  'already in',
  'ya existe',
  'ya sigues',
  'ya está',
  'duplicad',
];

/**
 * Detecta los errores de redirect internos de Next.js (digest NEXT_REDIRECT).
 * Los catch de cliente deben re-lanzarlos (`if (isNextRedirectError(e)) throw e`)
 * en vez de tragarlos con un toast: forman parte de la navegación.
 */
export function isNextRedirectError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const digest = (error as { digest?: unknown }).digest;
  return typeof digest === 'string' && digest.includes('NEXT_REDIRECT');
}

/**
 * Clasifica un error en una causa accionable:
 * - `stale`: cliente desfasado tras un despliegue (se evalúa PRIMERO, antes
 *   que los genéricos `offline`, porque comparte vocabulario con ellos).
 * - `offline`: motor/backend caído o red → el usuario puede reintentar.
 * - `duplicate`: el recurso ya estaba (watchlist, alerta...).
 * - `validation` / `auth` / `not_found`: errores de negocio conocidos.
 */
export function classifyError(error: unknown): ErrorCause {
  if (error instanceof AppError) {
    if (error.code === 'EXTERNAL_API_ERROR') return 'offline';
    if (error.code === 'RESEARCH_API_ERROR' && error.statusCode >= 500) return 'offline';
    if (error.code === 'VALIDATION_ERROR') return 'validation';
    if (error.code === 'AUTH_ERROR' || error.code === 'AUTHORIZATION_ERROR') return 'auth';
    if (error.code === 'NOT_FOUND') return 'not_found';
    if (error.code === 'DUPLICATE_ERROR') return 'duplicate';
  }
  const message = getErrorMessage(error).toLowerCase();
  if (STALE_MARKERS.some((marker) => message.includes(marker))) return 'stale';
  if (NEXT_PROD_GENERIC_MARKERS.some((marker) => message.includes(marker))) return 'offline';
  if (OFFLINE_MARKERS.some((marker) => message.includes(marker))) return 'offline';
  if (DUPLICATE_MARKERS.some((marker) => message.includes(marker))) return 'duplicate';
  return 'unknown';
}

/** Traducciones de mensajes backend/cliente habituales al español */
const MESSAGE_TRANSLATIONS: Array<[RegExp, string]> = [
  [/^a valid ticker is required$/i, 'Introduce un ticker válido.'],
  [/^invalid alert id$/i, 'Identificador de alerta no válido.'],
  [/^authentication failed$/i, 'Necesitas iniciar sesión para continuar.'],
  [/^access denied$/i, 'No tienes permiso para esta operación.'],
  [/^rate limit exceeded$/i, 'Demasiadas peticiones. Espera un momento y reintenta.'],
  [/^an unexpected error occurred$/i, 'Ha ocurrido un error inesperado.'],
  [/^an unknown error occurred$/i, 'Ha ocurrido un error inesperado.'],
  [/not found$/i, 'no encontrado'],
  [/unexpected response/i, 'El motor de análisis no responde ahora mismo.'],
];

const DEFAULT_UNKNOWN_MESSAGE = 'No se pudo completar la operación. Inténtalo de nuevo.';

/**
 * Mensaje de error en español y accionable para toasts:
 * - `stale` → "nueva versión, recarga".
 * - `offline` → "motor no disponible, reintenta".
 * - `duplicate` → "ya sigues este ticker" (o `options.duplicateMessage`).
 * - resto → traducción del mensaje de negocio o fallback genérico
 *   (el detalle crudo queda en consola para depurar).
 */
export function getFriendlyErrorMessage(
  error: unknown,
  options: { duplicateMessage?: string } = {},
): string {
  const cause = classifyError(error);
  if (cause === 'stale') {
    return 'Hay una nueva versión de la app: recarga la página.';
  }
  if (cause === 'offline') {
    return 'El motor de análisis no responde ahora mismo. Reintenta en unos segundos.';
  }
  if (cause === 'duplicate') {
    return options.duplicateMessage ?? 'Ya sigues este ticker.';
  }

  const message = getErrorMessage(error);
  for (const [pattern, replacement] of MESSAGE_TRANSLATIONS) {
    if (pattern.test(message)) {
      return replacement.endsWith('no encontrado')
        ? `${message.replace(pattern, replacement)}`
        : replacement;
    }
  }

  if (cause === 'unknown') {
    // Mensajes crudos en inglés del runtime no deben llegar a la UI.
    if (/[a-z]{4,}/i.test(message) && !/[áéíóúñ¿¡]/i.test(message) && message.split(' ').length > 12) {
      console.error('[error no mostrado en UI]', error);
      return DEFAULT_UNKNOWN_MESSAGE;
    }
  }
  return message || DEFAULT_UNKNOWN_MESSAGE;
}
