/**
 * Textos de error del motor (FastAPI `detail`) en español para la UI.
 *
 * El backend responde muchos rechazos en inglés («Holding not found»,
 * «Tenant context required», «500 Internal Server Error»…) y varios caminos
 * los pintaban tal cual: la página de cartera, los resultados de las server
 * actions y los toasts («Holding no encontrado», mezcla de idiomas). Se
 * traduce en la frontera de la UI, no en `researchRequest`, porque hay lógica
 * que reconoce el texto original del motor (p. ej. `ledgerRejection`).
 *
 * Regla: lo conocido se traduce; lo que siga pareciendo inglés se sustituye
 * por un aviso genérico en español; el español del motor pasa intacto.
 */

// Ruta relativa con extensión .ts: este módulo se importa desde tests con node --test.
// @ts-expect-error TS5097
import { knownBackendMessageEn } from './backend-error-en.ts';
// Import relativo con atributo, igual que lib/research/shorts-text.ts: los
// textos viven en los diccionarios y aquí solo se cruzan, así el guard de
// i18n no cuenta literales de este archivo y los techos no se tocan.
import esErrors from '../i18n/messages/es/errors.json' with { type: 'json' };

// Validaciones pydantic de cartera, alertas y plan (llegan como texto de
// `detail` cuando la ruta hace `HTTPException(detail=str(exc))`).
type ValidationKey = keyof typeof esErrors.backendValidation;

// Uso por literal para el guard de i18n (claves consumidas por iteración,
// igual que SHORTS_BACKEND_TEXT_KEY_LITERALS): sin estas cadenas el guard
// las marcaría como huérfanas nuevas.
export const BACKEND_ERROR_VALIDATION_KEY_LITERALS = [
  'errors.backendValidation.currencyCode',
  'errors.backendValidation.currencyIso',
  'errors.backendValidation.baseCurrencyIso',
  'errors.backendValidation.feesDecimals',
  'errors.backendValidation.tradeDateFuture',
  'errors.backendValidation.dateFuture',
  'errors.backendValidation.finiteNumber',
  'errors.backendValidation.min6Decimals',
  'errors.backendValidation.min10Decimals',
] as const;

/** Mensaje exacto del motor (en minúsculas) → clave de diccionario. */
const VALIDATION_MESSAGES: [string, ValidationKey][] = [
  ['currency must be a currency code such as eur, usd or gbp', 'currencyCode'],
  ['currency must be an iso 4217 code such as eur or usd', 'currencyIso'],
  ['base_currency must be an iso 4217 code such as eur or usd', 'baseCurrencyIso'],
  ['fees allow at most 4 decimal places', 'feesDecimals'],
  ['trade_date cannot be in the future', 'tradeDateFuture'],
  ['date cannot be in the future', 'dateFuture'],
  ['value must be a finite number', 'finiteNumber'],
  ['must be at least 0.000001 (6 decimal places)', 'min6Decimals'],
  ['must be at least 0.0000000001 (10 decimal places)', 'min10Decimals'],
];

// Sin genéricos con ángulos ni flechas antes de EXACT: un `>` seguido más
// abajo de un `<` crea un falso nodo JSX para el guard de i18n y le infla
// el recuento de literales.
const validationTexts: { [key: string]: string } = esErrors.backendValidation;

const GENERIC = 'No se pudo completar la operación. Inténtalo de nuevo.';
const ENGINE_DOWN = 'El motor de análisis no responde ahora mismo. Reintenta en unos segundos.';
const NOT_FOUND_GENERIC = 'No se encontró lo que buscas (puede que se haya borrado). Recarga la página.';

/** Textos exactos del motor (en minúsculas) → español. */
const EXACT: Record<string, string> = {
  'insufficient shares for sale': 'No puedes vender más acciones de las que tienes en cartera.',
  'position cannot mix transaction currencies': 'Esta posición ya tiene movimientos en otra divisa: usa la misma divisa que los anteriores.',
  'tenant context required': 'Tu sesión no está lista. Recarga la página o vuelve a iniciar sesión.',
  'no thesis for ticker': 'Esta empresa aún no tiene tesis.',
  'no published thesis for ticker': 'Esta empresa aún no tiene una tesis publicada.',
  'knowledge rag is disabled': 'La búsqueda en la biblioteca no está activada.',
  'knowledge index unavailable': 'El índice de la biblioteca no está disponible ahora mismo.',
  'ingestion queue is unavailable': 'La cola de procesamiento no está disponible ahora mismo. Reintenta más tarde.',
  'knowledge collection is not empty': 'La colección no está vacía: borra antes sus documentos.',
  'knowledge collection already exists': 'Ya existe una colección con ese nombre.',
  'document chunk does not belong to document': 'Ese fragmento no pertenece al documento.',
  'url ingestion failed': 'No se pudo importar la URL.',
  'document ingestion failed': 'No se pudo procesar el documento.',
  'knowledge ingestion failed': 'No se pudo procesar el documento.',
  'unknown driver; build the company model first': 'Primero hay que construir el modelo de la empresa.',
  'at least one revision field is required': 'Indica al menos un campo que cambiar.',
  'no red-team run found': 'Aún no hay revisión crítica para esta tesis.',
  'year must be between 2000 and 2200': 'El año debe estar entre 2000 y 2200.',
  'fiscal_year must be between 2000 and 2200': 'El año fiscal debe estar entre 2000 y 2200.',
  'rate limit exceeded': 'Demasiadas peticiones. Espera un momento y reintenta.',
  'quantity must be positive and price cannot be negative': 'La cantidad debe ser positiva y el precio no puede ser negativo.',
  'fees cannot be negative': 'Las comisiones no pueden ser negativas.',
  'authentication backend unavailable': 'El servicio de autenticación no está disponible ahora mismo. Reintenta en unos segundos.',
  'rate limit backend unavailable': 'El servicio de control de peticiones no está disponible ahora mismo. Reintenta en unos segundos.',
  'research authentication is not configured': 'El motor de análisis no está configurado todavía. Inténtalo más tarde.',
  'tenant access is not active': 'Tu cuenta no está activa. Cierra sesión y vuelve a entrar; si sigue fallando, contacta con soporte.',
};

// Las validaciones pydantic se cruzan desde el diccionario (ver arriba).
for (const [message, key] of VALIDATION_MESSAGES) EXACT[message] = validationTexts[key];

/** Sujeto de «X not found» → español. */
const NOT_FOUND_SUBJECT: Record<string, string> = {
  company: 'No se encontró la empresa.',
  holding: 'Esa posición ya no existe. Recarga la página.',
  transaction: 'Ese movimiento ya no existe (quizá se borró en otra pestaña). Recarga la página.',
  alert: 'Esa alerta ya no existe. Recarga la página.',
  'alert rule': 'Esa alerta ya no existe. Recarga la página.',
  contribution: 'Esa aportación ya no existe. Recarga la página.',
  document: 'No se encontró el documento.',
  'knowledge document': 'No se encontró el documento.',
  'knowledge collection': 'No se encontró la colección.',
  'saved screen': 'Ese screener guardado ya no existe.',
  'news event': 'No se encontró la noticia.',
  investor: 'No se encontró el inversor.',
  thesis: 'No se encontró la tesis.',
  'thesis version': 'No se encontró esa versión de la tesis.',
  job: 'No se encontró la tarea.',
  'processing job': 'No se encontró la tarea.',
  claim: 'No se encontró la afirmación.',
  'corporate action': 'No se encontró la acción corporativa.',
  'decision lesson': 'No se encontró la lección de decisiones.',
  'investment principle': 'No se encontró el principio de inversión.',
  'kpi candidate': 'No se encontró el candidato de KPI.',
  'management promise': 'No se encontró el compromiso de la directiva.',
  'propick run': 'No se encontró la ejecución de ProPicks.',
  'research session': 'No se encontró la sesión de investigación.',
  review: 'No se encontró la revisión.',
  source: 'No se encontró la fuente.',
};

const SPANISH_MARKS = /[áéíóúñü¿¡«»]/i;
const ENGLISH_WORDS =
  /\b(the|not|found|for|is|are|must|cannot|can't|failed|required|invalid|unavailable|already|exists|disabled|unknown|missing|error|only|does|belong|between|least|request|internal|server|gateway|service|unauthorized|forbidden|bad|too|many|unprocessable|entity|timeout|engine)\b/i;

/** true si el texto parece inglés (sin marcas del español y con palabras inglesas). */
export function looksEnglish(message: string): boolean {
  const text = message.trim();
  if (!text || SPANISH_MARKS.test(text)) return false;
  // snake_case de código interno («plan_currency_required_for_amount_change»).
  if (/^[a-z0-9]+(_[a-z0-9]+)+$/.test(text)) return true;
  return ENGLISH_WORDS.test(text.replace(/_/g, ' '));
}

function byStatus(status: number): string {
  if (status === 404) return NOT_FOUND_GENERIC;
  if (status === 401) return 'Necesitas iniciar sesión para continuar.';
  if (status === 403) return 'No tienes permiso para esta operación.';
  if (status === 409) return 'La operación choca con el estado actual. Recarga la página y revisa los datos.';
  if (status === 400 || status === 422) return 'El motor de análisis rechazó los datos enviados. Revisa el formulario y vuelve a intentarlo.';
  if (status === 429) return EXACT['rate limit exceeded'];
  if (status >= 500) return ENGINE_DOWN;
  return GENERIC;
}

export function spanishBackendMessage(message: string | null | undefined, fallback: string = GENERIC): string {
  const text = (message ?? '').trim();
  if (!text) return fallback;
  // Pydantic antepone «Value error, » a los ValueError de validación.
  const key = text.replace(/^Value error,\s*/i, '').toLowerCase().replace(/[.\s]+$/, '');
  if (EXACT[key]) return EXACT[key];

  // «404 Not Found», «500 Internal Server Error» (cuerpo sin detail).
  const status = /^(\d{3})(\s+[A-Za-z' -]*)?$/.exec(text);
  if (status) return byStatus(Number(status[1]));

  if (/^research engine unavailable\b/i.test(text)) return ENGINE_DOWN;

  // «Company AAPL not found», «Workflow 'x' not found», «Holding not found».
  const notFound = /^(.+?) not found$/i.exec(key);
  if (notFound) {
    const raw = notFound[1].replace(/^(to|from)\s+/, '').replace(/\s+'[^']*'$/, '');
    const subject = NOT_FOUND_SUBJECT[raw] ? raw : raw.split(/\s+/).slice(0, -1).join(' ');
    return NOT_FOUND_SUBJECT[subject] ?? NOT_FOUND_GENERIC;
  }

  // «Thesis generation failed (ref abc123)»: se conserva la referencia.
  const ref = /\(ref ([\w-]+)\)\s*$/i.exec(text);
  if (looksEnglish(text)) {
    return ref ? `${fallback} (ref ${ref[1]})` : fallback;
  }
  return text;
}

/* ------------------------------------------------------------------ *
 * Inglés (Ajustes → Idioma = English). El motor ya habla inglés: lo legible
 * pasa tal cual (con mayúscula y punto); los códigos snake_case y los
 * «500 Internal Server Error» se sustituyen por un aviso en inglés, y el
 * español que devuelva el motor pasa intacto (no se traduce prosa).
 * ------------------------------------------------------------------ */

const EN_GENERIC = 'The operation could not be completed. Please retry.';
const EN_ENGINE_DOWN = 'The analysis engine is not responding right now. Retry in a few seconds.';

function englishByStatus(status: number): string {
  if (status === 404) return 'What you are looking for could not be found (it may have been deleted). Reload the page.';
  if (status === 401) return 'You need to sign in to continue.';
  if (status === 403) return 'You do not have permission for this operation.';
  if (status === 409) return 'The operation conflicts with the current state. Reload the page and check the data.';
  if (status === 400 || status === 422) return 'The analysis engine rejected the data sent. Check the form and retry.';
  if (status === 429) return 'Too many requests. Wait a moment and retry.';
  if (status >= 500) return EN_ENGINE_DOWN;
  return EN_GENERIC;
}

/** Mensaje del motor para el idioma de la interfaz; en español, lo mismo que `spanishBackendMessage`. */
export function backendMessage(
  message: string | null | undefined,
  locale: 'es' | 'en' = 'es',
  fallback?: string,
): string {
  if (locale !== 'en') return spanishBackendMessage(message, fallback);
  const text = (message ?? '').trim();
  const englishFallback = fallback ?? EN_GENERIC;
  if (!text) return englishFallback;
  const status = /^(\d{3})(\s+[A-Za-z' -]*)?$/.exec(text);
  if (status) return englishByStatus(Number(status[1]));
  if (/^research engine unavailable\b/i.test(text)) return EN_ENGINE_DOWN;
  if (/^[a-z0-9]+(_[a-z0-9]+)+$/.test(text)) return englishFallback;
  const known = knownBackendMessageEn(text);
  if (known) return known;
  if (SPANISH_MARKS.test(text)) return text;
  const sentence = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?)]$/.test(sentence) ? sentence : `${sentence}.`;
}
