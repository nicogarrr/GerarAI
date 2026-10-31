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
  const key = text.toLowerCase().replace(/[.\s]+$/, '');
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
