// Ruta relativa con extensión .ts a propósito (no '@/...'): redact.ts es un
// módulo puro y este archivo se importa desde tests con node --test
// (--experimental-strip-types), que no resuelve alias ni añade extensiones.
// @ts-expect-error TS5097
import { redactSecretsInText } from '../upstream/redact.ts';
// @ts-expect-error TS5097
import { backendMessage } from '../research/backend-error-es.ts';
// @ts-expect-error TS5097
import { DEFAULT_LOCALE, type Locale } from '../i18n/locale.ts';
import type { TranslationKey } from '../i18n/t.ts';
// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';
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
 * Variante para texto que va AL CLIENTE: igual que getErrorMessage pero con
 * credenciales redactadas. Los errores de fetch/httpx llevan la URL completa
 * del proveedor (?token=, ?apikey=...) en el message, y un DSN lleva la
 * password en el userinfo: sin esta capa la clave del servidor llegaba al
 * navegador. El detalle completo queda en el log del servidor
 * (console.error), nunca en la respuesta.
 */
export function getSafeErrorMessage(error: unknown): string {
  return redactSecretsInText(getErrorMessage(error));
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
  // Prefijo/detalle que genera lib/research/client.ts cuando falla el
  // motor. Al cruzar la frontera de una server action el AppError
  // pierde su code y solo queda el mensaje: sin estos marcadores el
  // texto crudo (ingles + ruta interna) llegaba al toast.
  'research engine unavailable',
  'fetch fallido',
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
const MESSAGE_TRANSLATIONS: Array<[RegExp, TranslationKey]> = [
  [/^a valid ticker is required$/i, 'errors.friendly.invalidTicker'],
  [/^invalid alert id$/i, 'errors.friendly.invalidAlertId'],
  [/^authentication failed$/i, 'errors.friendly.signIn'],
  [/^access denied$/i, 'errors.friendly.forbidden'],
  [/^rate limit exceeded$/i, 'errors.friendly.rateLimit'],
  [/^an unexpected error occurred$/i, 'errors.friendly.unexpected'],
  [/^an unknown error occurred$/i, 'errors.friendly.unexpected'],
  [/unexpected response/i, 'errors.friendly.engineDown'],
];

/**
 * Mensaje de error para la UI en el idioma elegido (Ajustes → Idioma). Sin
 * `locale` queda en español, como siempre.
 */
export function getFriendlyErrorMessage(
  error: unknown,
  options: { duplicateMessage?: string; locale?: Locale } = {},
): string {
  const locale = options.locale ?? DEFAULT_LOCALE;
  const t = createTranslator(locale);
  const cause = classifyError(error);
  if (cause === 'stale') {
    return t('errors.friendly.stale');
  }
  if (cause === 'offline') {
    return t('errors.friendly.offline');
  }
  if (cause === 'duplicate') {
    return options.duplicateMessage ?? t('errors.friendly.duplicateTicker');
  }

  // Sesión caducada o sin permiso: el mensaje interno ('User not
  // authenticated', 'Access denied'...) está en inglés y no dice qué hacer.
  // Se traduce por código, no por texto, para que ningún 401/403 local llegue
  // crudo a un toast.
  if (cause === 'auth' && error instanceof AppError) {
    return error.code === 'AUTHORIZATION_ERROR'
      ? t('errors.friendly.forbidden')
      : t('errors.friendly.signIn');
  }

  const message = getErrorMessage(error);
  for (const [pattern, key] of MESSAGE_TRANSLATIONS) {
    if (pattern.test(message)) return t(key);
  }

  // Textos del motor en inglés («Holding not found», «Tenant context
  // required»…): en español, traducidos o aviso genérico; en inglés, la frase
  // legible del motor o un aviso genérico en inglés.
  const shown = backendMessage(message, locale, t('errors.friendly.unknown'));
  if (shown !== message) console.error('[error traducido para la UI]', error);
  return shown;
}
