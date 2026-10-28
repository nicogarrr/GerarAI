/**
 * Helpers únicos de formateo para toda la app (es-ES).
 *
 * Toda cifra, fecha o importe visible en UI debe pasar por aquí: evita la
 * mezcla de formatos en-US/es-ES detectada en la auditoría de frontend y
 * garantiza separadores de miles/meses españoles en todos los viewports.
 */

export const FORMAT_LOCALE = 'es-ES';

/** Zona del mercado de referencia: cierres, velas y datos de cotizaciones. */
export const MARKET_TZ = 'America/New_York';

/** Zona del usuario: todo lo que es "su" fecha (suscripción, tenencias, CFD). */
export const USER_TZ = 'Europe/Madrid';

/** Valor numérico tolerante (string de backend, null, undefined) */
export type NumericInput = number | string | null | undefined;

/** Placeholder unificado para valores ausentes */
export const NA = 'N/D';

/**
 * Placeholder unificado para ESTADOS DE FLUJO: la tesis aún no se ha
 * generado, el job está en cola, la promesa no se ha conciliado.
 *
 * Por qué NO reutilizamos `NA` aunque los dos mean "no hay valor": `NA` dice
 * que el dato NO EXISTE o no se pudo traer y siempre arrastra un CTA de
 * reintento; `NO_CORRIDO` dice que el dato AÚN NO SE HA CALCULADO y no
 * lleva acción posible. Un token común impediría al usuario —y a soporte—
 * distinguir "GerarAI está roto" de "todavía no lo has pedido".
 */
export const NO_CORRIDO = 'No corrido';

function toFinite(value: NumericInput): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export type LocalizedNumberError = 'empty' | 'invalid' | 'ambiguous';

const INT_PLAIN = /^\d+$/;
// Miles es-ES estrictos: grupos de 3 tras el primero («1.234», «12.345.678»).
const INT_GROUPS_ES = /^\d{1,3}(?:\.\d{3})+$/;

/**
 * Parsea números escritos por el usuario en formato es-ES sin adivinar.
 *
 * Gramática admitida:
 * - «32,5» / «1.234,56» / «12.345.678,9»: coma decimal, punto solo como
 *   separador de miles en grupos exactos de 3 antes de la coma.
 * - «1.234» -> 1234 (miles es-ES) y «1234.56» / «32.5» -> decimal con punto
 *   cuando el punto NO forma grupos de 3.
 * - Signo «-» inicial opcional.
 *
 * Se RECHAZA (error, nunca un valor reinterpretado) todo formato ambiguo:
 * - «1,234.5» (orden US mezclado) y «1,234» (¿1.234 es ó 1234 US?): antes
 *   «1,234.5» se leía como 1,2345, un factor 1000 silencioso en dinero.
 *   Excepción: «0,001» es decimal (nadie agrupa miles con un 0 delante).
 * - «1e3», «0x10», «1 000», «Infinity»: Number() los aceptaba en silencio.
 *
 * El error «ambiguous» permite al formulario explicar el formato esperado
 * en lugar del genérico «introduce un número válido».
 */
export function parseLocalizedNumberDetailed(
  value: string,
): { ok: true; value: number } | { ok: false; error: LocalizedNumberError } {
  const trimmed = value.trim();
  if (!trimmed) return { ok: false, error: 'empty' };
  const negative = trimmed.startsWith('-');
  const body = negative ? trimmed.slice(1) : trimmed;
  const finish = (magnitude: number) => {
    const signed = negative ? -magnitude : magnitude;
    return Number.isFinite(signed)
      ? { ok: true as const, value: signed }
      : { ok: false as const, error: 'invalid' as const };
  };

  const commaParts = body.split(',');
  if (commaParts.length > 2) return { ok: false, error: 'ambiguous' };
  if (commaParts.length === 2) {
    const [intPart, decPart] = commaParts;
    if (!INT_PLAIN.test(decPart)) return { ok: false, error: 'ambiguous' }; // «1,234.5», «32,», «1,2e3»
    if (intPart === '') return finish(Number(`0.${decPart}`)); // «,5»
    if (INT_GROUPS_ES.test(intPart)) {
      return finish(Number(`${intPart.replace(/\./g, '')}.${decPart}`)); // «1.234,56»
    }
    if (INT_PLAIN.test(intPart)) {
      // Coma seguida de exactamente 3 dígitos («1,234»): ¿decimal es-ES 1,234
      // o miles US 1234? Ambiguo y en dinero no se adivina; «0,001» sí es
      // decimal porque los miles nunca empiezan por 0.
      if (decPart.length === 3 && intPart !== '0') return { ok: false, error: 'ambiguous' };
      return finish(Number(`${intPart}.${decPart}`));
    }
    return { ok: false, error: 'ambiguous' }; // «12.34,5»: grupo de miles roto
  }

  const dotParts = body.split('.');
  if (dotParts.length === 1) {
    if (!INT_PLAIN.test(body)) return { ok: false, error: 'invalid' }; // «1e3», «abc», «0x10», «1 000», «+3», «-»
    return finish(Number(body));
  }
  if (dotParts.some((part) => part === '')) {
    // «.5» y «5.» se admiten; «1..2» no.
    if (dotParts.length === 2 && INT_PLAIN.test(dotParts[0] + dotParts[1])) {
      return finish(Number(`${dotParts[0] || '0'}.${dotParts[1] || '0'}`));
    }
    return { ok: false, error: 'ambiguous' };
  }
  if (dotParts.length > 2) {
    if (INT_GROUPS_ES.test(body)) return finish(Number(body.replace(/\./g, ''))); // «1.234.567»
    return { ok: false, error: 'ambiguous' };
  }
  // Un solo punto: grupos de 3 = miles es-ES («1.234» -> 1234); si no,
  // decimal con punto («32.5», «1.23», «1.2345»).
  if (INT_GROUPS_ES.test(body)) return finish(Number(body.replace(/\./g, '')));
  return finish(Number(body));
}

/**
 * Parsea números escritos por el usuario tolerando el formato es-ES.
 * Devuelve null ante entrada vacía, inválida o AMBIGUA (nunca reinterpreta:
 * mejor un error visible que un factor 1000 silencioso en dinero). Para
 * distinguir el motivo y mensajear al usuario, usa parseLocalizedNumberDetailed.
 */
export function parseLocalizedNumber(value: string): number | null {
  const result = parseLocalizedNumberDetailed(value);
  return result.ok ? result.value : null;
}

/**
 * Precarga de inputs numéricos: el number del backend (p.ej. 6.0572 o 1e-7)
 * se escribe con la gramática es-ES del formulario («6,0572», «0,0000001»),
 * nunca con Number.toString() («6.0572», «1e-7»), que el propio parser del
 * formulario rechazaría o mostraría con punto decimal en una UI en español.
 * Sin separador de miles para no estorbar al editar; hasta 12 decimales para
 * que el valor sobreviva al round-trip guardar-sin-tocar. No finito -> ''.
 */
export function formatNumberForInput(value: number): string {
  if (!Number.isFinite(value)) return '';
  return new Intl.NumberFormat(FORMAT_LOCALE, {
    useGrouping: false,
    maximumFractionDigits: 12,
  }).format(value);
}

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  // "YYYY-MM-DD" es UTC midnight para `new Date(string)`: en un TZ negativo se
  // ve el día anterior. Se parsea como fecha local explícita (día del ledger,
  // fecha de transacción, vencimiento de CFD: son días de calendario, no
  // instantes). Cualquier otra cadena (ISO con hora, etc.) sí es un instante.
  const dateOnly = typeof value === 'string' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  const date = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Número con separadores españoles (1.234,56).
 * Acepta `Intl.NumberFormatOptions` para decimales/notación.
 */
export function formatNumber(
  value: NumericInput,
  options: Intl.NumberFormatOptions = {},
  fallback: string = NA,
): string {
  const parsed = toFinite(value);
  if (parsed === null) return fallback;
  return new Intl.NumberFormat(FORMAT_LOCALE, {
    maximumFractionDigits: 2,
    useGrouping: 'always',
    ...options,
  }).format(parsed);
}

/**
 * Código de divisa aceptado por Intl (ISO 4217). Una divisa ausente o rara
 * NUNCA se sustituye por USD: el dato que la necesita se omite.
 */
export function isValidCurrencyCode(currency: string | null | undefined): currency is string {
    if (!currency || !/^[A-Z]{3}$/.test(currency)) return false;
    try {
        new Intl.NumberFormat(FORMAT_LOCALE, { style: 'currency', currency });
        return true;
    } catch {
        return false;
    }
}

/**
 * Confianza de un dato como porcentaje (0.9 -> «90%»), con la regla del repo:
 * sin dato o no finito es N/D, nunca un «0%» inventado. `Number(null) * 100`
 * da 0 y `Number(undefined) * 100` da NaN; pintarlos como confianza medida
 * engaña (hoy el esquema no deja nulos, mañana puede dejarlos).
 */
export function formatConfidence(value: NumericInput, fallback: string = NA): string {
  const parsed = toFinite(value);
  return parsed === null ? fallback : `${Math.round(parsed * 100)}%`;
}

/**
 * Importe monetario: USD en inglés ($1,234.56, como el resto de la app); otras divisas en es-ES (1.234,56 €).
 */
export function formatMoney(
  value: NumericInput,
  currency = 'USD',
  options: Intl.NumberFormatOptions = {},
  fallback: string = NA,
): string {
  const parsed = toFinite(value);
  if (parsed === null) return fallback;
  return new Intl.NumberFormat(currency === 'USD' ? 'en-US' : FORMAT_LOCALE, {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
    useGrouping: 'always',
    ...options,
  }).format(parsed);
}

/**
 * Precio: USD en inglés ($93.90), otras divisas con su locale español.
 * Decimales dinámicos: los valores muy pequeños (microcaps,
 * abs < 0,01) necesitan más de 2 decimales para no salir como "0,00 US$"
 * cuando el precio real es distinto de cero (F35, SANW 0,0011 US$).
 * Por debajo de 0,01 se usan dígitos significativos en vez de decimales fijos.
 */
export function formatPrice(
  value: NumericInput,
  currency = 'USD',
  options: Intl.NumberFormatOptions = {},
  fallback: string = NA,
): string {
  const parsed = toFinite(value);
  if (parsed === null) return fallback;
  const small = parsed !== 0 && Math.abs(parsed) < 0.01;
  return new Intl.NumberFormat(currency === 'USD' ? 'en-US' : FORMAT_LOCALE, {
    style: 'currency',
    currency,
    useGrouping: 'always',
    ...(small
      ? { maximumSignificantDigits: 4 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    ...options,
  }).format(parsed);
}

/**
 * Cifra compacta en español (1,2 M · 3,4 mil M) para métricas y market caps.
 *
 * Intl es-ES con notation "compact" es inconsistente para miles de millones:
 * 9.447.000.000 se renderiza como "9447 M" mientras que 416.160.000.000 sale
 * como "416,16 mil M" (B18). Aquí la escala se fija siempre: millones como
 * "M" y miles de millones como "mil M", con decimales es-ES.
 */
export function formatCompact(
  value: NumericInput,
  options: Intl.NumberFormatOptions = {},
  fallback: string = NA,
): string {
  const parsed = toFinite(value);
  if (parsed === null) return fallback;
  const abs = Math.abs(parsed);
  const { maximumFractionDigits = 2, ...rest } = options;
  // La escala se elige con la cifra YA redondeada (ECMA-402, notation
  // «compact»): 999.999.999 redondea a 1.000 M y debe salir «1 mil M».
  const digits = Math.min(Math.max(Math.trunc(maximumFractionDigits), 0), 20);
  const roundsTo = (scaled: number) => Number(scaled.toFixed(digits));
  if (abs >= 1e9 || roundsTo(abs / 1e6) >= 1000) {
    return `${formatNumber(parsed / 1e9, { maximumFractionDigits, ...rest }, fallback)} mil M`;
  }
  if (abs >= 1e6 || roundsTo(abs) >= 1e6) {
    return `${formatNumber(parsed / 1e6, { maximumFractionDigits, ...rest }, fallback)} M`;
  }
  return new Intl.NumberFormat(FORMAT_LOCALE, {
    notation: 'compact',
    maximumFractionDigits,
    useGrouping: 'always',
    ...rest,
  }).format(parsed);
}

/**
 * Capitalización en USD, con la escala inglesa elegida por el usuario ($4.87B).
 * Solo presentación: el llamante garantiza que el importe ya está en dólares.
 * No usar para volúmenes o cantidades de acciones.
 */
export function formatMarketCapUsd(value: NumericInput, fallback: string = NA): string {
  const parsed = toFinite(value);
  if (parsed === null) return fallback;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(parsed);
}

/**
 * Porcentaje en español. Por defecto `value` es ratio (0.15 -> 15,0 %);
 * con `fromRatio: false` ya viene en tanto por ciento (15 -> 15,0 %).
 */
/**
 * Capitalización en la divisa real de la compañía (backend research la
 * conoce; USD solo cuando la divisa consta como USD). Compacta.
 */
export function formatMarketCap(value: NumericInput, currency: string | null, fallback: string = NA): string {
  const parsed = toFinite(value);
  if (parsed === null) return fallback;
  // Sin divisa real no se asume USD: numero compacto pelado, sin simbolo.
  if (!currency) {
    return new Intl.NumberFormat('es-ES', {
      notation: 'compact',
      maximumFractionDigits: 2,
    }).format(parsed);
  }
  // Locale segun divisa: EUR en es-ES (25,7 mil M EUR), USD en en-US.
  const locale = currency.toUpperCase() === 'USD' ? 'en-US' : 'es-ES';
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      minimumFractionDigits: 0,
      notation: 'compact',
      maximumFractionDigits: 2,
    }).format(parsed);
  } catch {
    return formatNumber(parsed, {}, fallback);
  }
}

export function formatPercent(
  value: NumericInput,
  { fromRatio = true, digits = 1, signDisplay }: { fromRatio?: boolean; digits?: number; signDisplay?: 'auto' | 'always' | 'never' } = {},
  fallback: string = NA,
): string {
  const parsed = toFinite(value);
  if (parsed === null) return fallback;
  const rawRatio = fromRatio ? parsed : parsed / 100;
  // A displayed zero is neutral, even if a tiny signed value rounds to zero.
  const roundedZero = Math.abs(rawRatio * 100) < 0.5 * 10 ** -digits;
  const ratio = roundedZero ? 0 : rawRatio;
  return new Intl.NumberFormat(FORMAT_LOCALE, {
    style: 'percent',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    ...(signDisplay ? { signDisplay: roundedZero && signDisplay === 'always' ? 'auto' : signDisplay } : {}),
  }).format(ratio);
}

/**
 * Conteo con concordancia es-ES: formatCountEs(1, 'posición', 'posiciones')
 * -> «1 posición»; formatCountEs(5, 'posición', 'posiciones') ->
 * «5 posiciones». El número lleva separador de miles es-ES.
 */
export function formatCountEs(value: number, singular: string, pluralForm: string): string {
  return `${formatNumber(value, { maximumFractionDigits: 0 })} ${value === 1 ? singular : pluralForm}`;
}

/**
 * Fecha corta en español (23 sept 2026). Acepta Date, ISO o timestamp.
 * Sin `timeZone` por defecto: el comportamiento actual no cambia para los
 * call sites existentes; para fechas con zona definida usa `formatUserDate`
 * o `formatMarketDate`.
 */
export function formatDate(
  value: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' },
  fallback: string = NA,
): string {
  const date = toDate(value);
  if (!date) return fallback;
  return new Intl.DateTimeFormat(FORMAT_LOCALE, options).format(date);
}

/** Cadena de solo fecha `YYYY-MM-DD`: dia de calendario, no instante. */
const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Fecha en la zona del mercado (cierre de una vela, fecha de cotización).
 *
 * Un string `YYYY-MM-DD` YA es el dia de calendario del mercado: se renderiza
 * literal (UTC fijo). Parsearlo como medianoche local y aplicar
 * America/New_York le RESTA UN DIA (medianoche en Madrid/UTC = tarde del dia
 * anterior en NY). Los instantes (ISO con hora, timestamps, Date) si se
 * convierten a la zona del mercado.
 */
export function formatMarketDate(
  value: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' },
  fallback: string = NA,
): string {
  const dateOnly = typeof value === 'string' ? DATE_ONLY_RE.exec(value) : null;
  if (dateOnly) {
    const literal = new Date(
      Date.UTC(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])),
    );
    return new Intl.DateTimeFormat(FORMAT_LOCALE, { ...options, timeZone: 'UTC' }).format(literal);
  }
  return formatDate(value, { ...options, timeZone: MARKET_TZ }, fallback);
}

/**
 * Fecha en la zona del usuario (fechas de calendario propias).
 */
export function formatUserDate(
  value: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' },
  fallback: string = NA,
): string {
  // Un string YYYY-MM-DD ya ES el dia de calendario (asOf de una tesis,
  // fecha de transaccion): renderizarlo literal, sin pasar por ninguna zona
  // (medianoche local parseada + USER_TZ puede desplazar el dia).
  const dateOnly = typeof value === 'string' ? DATE_ONLY_RE.exec(value) : null;
  if (dateOnly) {
    const literal = new Date(
      Date.UTC(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])),
    );
    return new Intl.DateTimeFormat(FORMAT_LOCALE, { ...options, timeZone: 'UTC' }).format(literal);
  }
  return formatDate(value, { ...options, timeZone: USER_TZ }, fallback);
}

/**
 * Fecha + hora en español (23 sept 2026, 18:30).
 */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  },
  fallback: string = NA,
): string {
  return formatDate(value, options, fallback);
}

/** Fecha + hora en la zona del mercado (hora de cierre de sesión). */
export function formatMarketDateTime(
  value: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  },
  fallback: string = NA,
): string {
  return formatDate(value, { ...options, timeZone: MARKET_TZ }, fallback);
}

/** Fecha + hora en la zona del usuario. */
/**
 * Etiqueta de fecha "generada el ..." para tesis y memos.
 *
 * Un timestamp PRESENTE pero invalido no debe caer en el fallback `NA`:
 * pintar "generada el N/D" enmascara un dato roto como si el dato
 * faltara. Guard explicito: fecha ausente o no parseable devuelve null
 * (la UI omite la etiqueta), solo una fecha valida se formatea.
 */
export function formatGeneratedDate(
  value: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' },
): string | null {
  if (value === null || value === undefined) return null;
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return formatUserDate(parsed, options);
}

export function formatUserDateTime(
  value: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  },
  fallback: string = NA,
): string {
  // "YYYY-MM-DD" es un día de calendario, no un instante: toDate() lo parsea como
  // medianoche en la zona del PROCESO (UTC en el servidor, Madrid en el navegador),
  // y al formatearlo en Madrid salía "02:00" en el SSR y "00:00" en el cliente
  // (React #418 en /risk, "Datos a fecha de"). Se pinta el día literal, sin hora.
  const dateOnly = typeof value === 'string' ? DATE_ONLY_RE.exec(value) : null;
  if (dateOnly) {
    const literal = new Date(
      Date.UTC(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])),
    );
    const { hour: _hour, minute: _minute, second: _second, ...dayOnly } = options;
    return new Intl.DateTimeFormat(FORMAT_LOCALE, { ...dayOnly, timeZone: 'UTC' }).format(literal);
  }
  return formatDate(value, { ...options, timeZone: USER_TZ }, fallback);
}

/**
 * "Hoy" del usuario en `YYYY-MM-DD`, listo para `<input type="date">`.
 *
 * `new Date().toISOString().split('T')[0]` devuelve el día en UTC: entre las
 * 22:00 y las 00:00 Europe/Madrid el servidor (UTC) da el día de mañana y el
 * navegador da el de hoy, así que el default del input difiere entre el HTML
 * del servidor y la hidratación.
 */
export function todayLocal(): string {
  // "Hoy" en la zona del USUARIO, no en la del proceso: con el servidor en
  // UTC y el navegador en Europe/Madrid, getFullYear()/getDate() daban dias
  // distintos entre el HTML del servidor y la hidratacion. `en-CA` rinde
  // YYYY-MM-DD directamente.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: USER_TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

/**
 * Tiempo relativo en español ("hace 3 días", "hace 12 minutos").
 * `timestamp` viene en segundos (formato de APIs de noticias).
 *
 * `now` permite pasar el instante de referencia calculado en el servidor: sin
 * él, `Date.now()` dentro del render rompe la hidratación en client
 * components (el servidor y el navegador pueden caer en buckets distintos).
 */
export function formatTimeAgo(
  timestamp: number | string | Date | null | undefined,
  now: number | Date = Date.now(),
): string {
  const date =
    timestamp instanceof Date || typeof timestamp === 'string'
      ? toDate(timestamp)
      : toFinite(timestamp) !== null
        ? new Date(toFinite(timestamp)! * 1000)
        : null;
  if (!date) return NA;
  const reference = now instanceof Date ? now.getTime() : now;
  const diffInMs = reference - date.getTime();
  const diffInMinutes = Math.max(0, Math.floor(diffInMs / (1000 * 60)));
  const diffInHours = Math.floor(diffInMinutes / 60);
  const diffInDays = Math.floor(diffInHours / 24);
  if (diffInDays > 0) return `hace ${diffInDays} ${diffInDays === 1 ? 'día' : 'días'}`;
  if (diffInHours >= 1) return `hace ${diffInHours} ${diffInHours === 1 ? 'hora' : 'horas'}`;
  if (diffInMinutes >= 1) {
    return `hace ${diffInMinutes} ${diffInMinutes === 1 ? 'minuto' : 'minutos'}`;
  }
  return 'ahora mismo';
}


/** Margen de seguridad para mostrar. MoS = (valor esperado - precio)/valor esperado, el estándar de Graham
 *  (no el potencial valor/precio - 1; base explícita en la UI): con un escenario base
 *  no positivo el numero (p. ej. -249 %) no es interpretable, asi que se muestra N/D
 *  en vez de un porcentaje que parece un dato. */
export function marginOfSafetyDisplay(
    margin: number | string | null | undefined,
    base: number | string | null | undefined,
): string {
    const baseNum = typeof base === 'string' ? Number(base) : base;
    if (baseNum !== null && baseNum !== undefined && !Number.isNaN(baseNum) && baseNum <= 0) return NA;
    const m = typeof margin === 'string' ? Number(margin) : margin;
    if (m === null || m === undefined || Number.isNaN(m)) return NA;
    return formatPercent(m);
}


const KEEP_UPPER = new Set(['ADR', 'ADS', 'ETF', 'REIT', 'SA', 'NV', 'AG', 'SE', 'ASA']);
const NAME_SUFFIXES: Record<string, string> = {
  INC: 'Inc', CORP: 'Corp', LTD: 'Ltd', PLC: 'plc', CO: 'Co', LLC: 'LLC', LP: 'LP',
  HOLDINGS: 'Holdings', GROUP: 'Group', TECHNOLOGIES: 'Technologies',
};

/**
 * Nombre de empresa legible: los proveedores a veces lo mandan todo en
 * mayúsculas («APPLE INC»). Si el nombre ya mezcla mayúsculas y minúsculas se
 * respeta tal cual; si viene todo en mayúsculas se pasa a «Apple Inc», dejando
 * las siglas de hasta tres letras (IBM, AMD) sin tocar.
 */
export function formatCompanyName(value: string | null | undefined): string {
  const raw = (value ?? '').trim();
  if (!raw) return NA;
  if (raw !== raw.toUpperCase()) return raw;
  const fixWord = (word: string): string => {
    if (!word) return word;
    if (NAME_SUFFIXES[word]) return NAME_SUFFIXES[word];
    // Finnhub recorta la descripción (~28 caracteres): «… LT» es «Ltd» cortado.
    if (KEEP_UPPER.has(word)) return word;
    if (word.length <= 3 || /[&\d]/.test(word)) return word;
    return word[0] + word.slice(1).toLowerCase();
  };
  const formatted = raw
    .split(/(\s+)/)
    .map((part) => {
      if (!part.trim()) return part;
      // respeta guiones y barras: «COCA-COLA» -> «Coca-Cola», «CORP/ADR» -> «Corp/ADR»
      return part
        .split(/([-/.,]+)/)
        .map((piece, idx) => (idx % 2 ? piece : fixWord(piece)))
        .join('');
    })
    .join('');
  // Solo la ÚLTIMA palabra, sin guion/barra delante: «… LT» es «Ltd» recortado.
  return /\s+LT$/.test(raw) ? formatted.replace(/\s+LT$/, ' Ltd') : formatted;
}
