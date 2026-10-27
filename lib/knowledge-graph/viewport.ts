/**
 * Matematica pura del viewport de /knowledge-graph (D2b).
 *
 * TODO lo que decide COMO se ve el grafo vive aqui y en ningun componente:
 * el lienzo solo aplica el resultado. Motivo: pan/zoom es donde se concentran
 * los bugs (zoom que se va solo al hacer zoom hacia el cursor, grafo que se
 * pierde fuera de la pantalla, division por cero con un unico nodo) y una
 * funcion pura se testea sin navegador.
 *
 * Convenciones (importan, estan):
 *  - `scale` es un factor sin dimension: 1 = 1 unidad de grafo por pixel CSS.
 *  - `x`/`y` son PIXELES DE PANTALLA (no unidades de grafo): por eso el
 *    arrastre suma el delta del puntero tal cual, sin dividir por el zoom.
 *  - La transformacion SVG es `translate(x y) scale(k)`, o sea un punto de
 *    grafo `g` se ve en pantalla en `x + k*g`. Todo el modulo usa esa misma
 *    convencion; `toSvgTransform` es la unica funcion que la escribe.
 *  - El lienzo mide su contenedor y renderiza el SVG 1 unidad de grafo = 1 px
 *    (`viewBox` igual al tamano medido). Sin esa equivalencia el anclaje del
 *    zoom al cursor necesitaria el factor de `preserveAspectRatio` y cualquier
 *    redondeo introduces deriva.
 *
 * Modulo puro: sin React, sin DOM, sin `window`. Se importa igual desde el
 * server component (para el deep link) y desde el cliente (para el arrastre).
 */

export type Point = { x: number; y: number };
export type Size = { width: number; height: number };
export type Viewport = { x: number; y: number; scale: number };
export type Bounds = { minX: number; minY: number; maxX: number; maxY: number };

/** Limites declarados del zoom. El minimo permite ver el grafo entero de una vez con margen; el maximo, leer las etiquetas de un nodo. */
export const MIN_SCALE = 0.25;
export const MAX_SCALE = 4;
/** Multiplicador de un paso de zoom (botones, rueda, teclado). */
export const ZOOM_STEP = 1.25;
/** Pixeles de desplazamiento por pulsacion de flecha. */
export const PAN_STEP = 48;
/** Margen (en unidades de grafo) que fitToView deja alrededor del contenido. */
export const FIT_PADDING = 24;
/** Fraccion del viewport que se puede arrastrar el grafo "fuera" antes de frenarse. */
export const OVERSCROLL = 0.15;

const EPSILON = 1e-9;

/** `NaN`/`Infinity` no deben viajar al atributo `transform` (el SVG lo descarta y el lienzo se congela). */
function finite(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function clamp(value: number, min: number, max: number): number {
  if (max < min) return min;
  return Math.min(max, Math.max(min, value));
}

export type ScaleLimits = { min?: number; max?: number };

/**
 * Limita la escala al rango declarado. Un rango invertido (min > max) se
 * corrige en vez de devolver una ventana vacia: un caller con limites
 * cambiados no debe poder dejar el grafo sin escala valida.
 *
 * `NaN` cae a 1 (no hay referencia de donde sair) y los infinitos se tratan
 * como lo que son: un exceso que se recorta al tope, no un error silencioso.
 */
export function clampScale(scale: number, limits: ScaleLimits = {}): number {
    const min = Math.max(EPSILON, finite(limits.min ?? MIN_SCALE, MIN_SCALE));
    const max = Math.max(min, finite(limits.max ?? MAX_SCALE, MAX_SCALE));
    if (Number.isNaN(scale)) return clamp(1, min, max);
    if (scale === Number.POSITIVE_INFINITY) return max;
    if (scale === Number.NEGATIVE_INFINITY) return min;
    return clamp(scale, min, max);
}

/** Caja que contiene todos los puntos. `null` si no hay puntos o ninguno es finito. */
export function boundsOf(points: readonly Point[]): Bounds | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let seen = false;
  for (const point of points) {
    const x = finite(point.x, NaN);
    const y = finite(point.y, NaN);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    seen = true;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return seen ? { minX, minY, maxX, maxY } : null;
}

export function boundsSize(bounds: Bounds): Size {
  return { width: Math.max(0, bounds.maxX - bounds.minX), height: Math.max(0, bounds.maxY - bounds.minY) };
}

export function expandBounds(bounds: Bounds, padding: number): Bounds {
  const pad = finite(padding, 0);
  return { minX: bounds.minX - pad, minY: bounds.minY - pad, maxX: bounds.maxX + pad, maxY: bounds.maxY + pad };
}

export function boundsCenter(bounds: Bounds): Point {
  return { x: (bounds.minX + bounds.maxX) / 2, y: (bounds.minY + bounds.maxY) / 2 };
}

export function isInsideBounds(point: Point, bounds: Bounds): boolean {
  return point.x >= bounds.minX && point.x <= bounds.maxX && point.y >= bounds.minY && point.y <= bounds.maxY;
}

/** Vista por defecto (sin nada calculado): escala 1 y sin desplazamiento. */
export function identityViewport(limits: ScaleLimits = {}): Viewport {
  return { x: 0, y: 0, scale: clampScale(1, limits) };
}

/**
 * Zoom anclado a un punto de pantalla: el punto indicado se queda pegado al
 * cursor mientras la escala cambia (comportamiento de mapa, no de "todo crece
 * desde la esquina"). Deriva continua de `pantalla = x + k*grafo`.
 *
 * Un factor no positivo devuelve la vista intacta: un gesto de pellizco
 * degenerado (dos dedos que se cruzan) no debe invertir el grafo.
 */
export function zoomAtPoint(viewport: Viewport, factor: number, anchor: Point, limits: ScaleLimits = {}): Viewport {
  if (!Number.isFinite(factor) || factor <= 0) return { ...viewport };
  const base = finite(viewport.scale, 1);
  const next = clampScale(base * factor, limits);
  const current = base > EPSILON ? base : 1;
  const ratio = next / current;
  const ax = finite(anchor.x, 0);
  const ay = finite(anchor.y, 0);
  return { x: ax - (ax - viewport.x) * ratio, y: ay - (ay - viewport.y) * ratio, scale: next };
}

/** Zoom alrededor del centro del lienzo (botones y teclado, sin puntero). */
export function zoomCentered(viewport: Viewport, factor: number, size: Size, limits: ScaleLimits = {}): Viewport {
  return zoomAtPoint(viewport, factor, { x: size.width / 2, y: size.height / 2 }, limits);
}

/**
 * Desplazamiento en PIXELES DE PANTALLA. No se divide por la escala a
 * proposito: arrastrar 100 px mueve 100 px aunque el grafo este al 400 %.
 */
export function panBy(viewport: Viewport, dx: number, dy: number): Viewport {
  return { x: viewport.x + finite(dx, 0), y: viewport.y + finite(dy, 0), scale: viewport.scale };
}

/**
 * Encaja `bounds` en el lienzo conservando la proporcion.
 *
 * Casos limite que se resuelven aqui y no en el caller:
 *  - Sin contenido o sin tamano medido: vista identidad (nada que encajar).
 *  - Caja de tamano 0 en un eje (un unico nodo, o todos en una fila): ese
 *    eje NO decide la escala, solo se centra. Si se dividiera entre 0 la
 *    escala seria Infinity o 0 y el grafo desapareceria.
 *  - La escala se acota al rango declarado: encajar 500 nodos nunca deja el
 *    lienzo a un 3 % ilegible.
 */
export function fitToView(bounds: Bounds | null, size: Size, padding: number = FIT_PADDING, limits: ScaleLimits = {}): Viewport {
  const width = Math.max(0, finite(size.width, 0));
  const height = Math.max(0, finite(size.height, 0));
  if (!bounds || width <= 0 || height <= 0) return identityViewport(limits);

  const padded = expandBounds(bounds, padding);
  const box = boundsSize(padded);
  const candidates: number[] = [];
  if (box.width > EPSILON && width > 0) candidates.push(width / box.width);
  if (box.height > EPSILON && height > 0) candidates.push(height / box.height);
  // Sin ningun eje con contenido (nodo unico y padding 0): escala 1.
  const raw = candidates.length ? Math.min(...candidates) : 1;
  const scale = clampScale(raw, limits);
  const center = boundsCenter(padded);
  return { x: width / 2 - center.x * scale, y: height / 2 - center.y * scale, scale };
}

/** Centra un punto de grafo conservando la escala actual. */
export function centerOnPoint(point: Point, size: Size, scale: number, limits: ScaleLimits = {}): Viewport {
  const next = clampScale(scale, limits);
  return { x: finite(size.width, 0) / 2 - finite(point.x, 0) * next, y: finite(size.height, 0) / 2 - finite(point.y, 0) * next, scale: next };
}

/**
 * Frena el arrastre para que el grafo no se pueda perder.
 *
 * El rango permitido en cada eje es `margen - max` .. `lienzo - margen - min`:
 * siempre queda un fragmento del grafo dentro del lienzo, con un margen
 * proporcional para poder tirar un poco "hacia fuera" y ver que hay borde.
 *
 * NO hay caso especial cuando el contenido es mas pequeño que el lienzo: el
 * rango sigue siendo valido (mas estrecho que el lienzo, pero no vacio) y el
 * grafo se puede desplazar. Bloquear ese eje estaba infusionado de "centrado
 * perpetuo": con el grafo entero visible, arrastrar no hacia NADA, que se
 * lee como un lienzo roto.
 *
 * Sin caja (grafo vacio): no se toca la vista.
 */
export function clampViewport(viewport: Viewport, bounds: Bounds | null, size: Size, overscroll: number = OVERSCROLL): Viewport {
    if (!bounds) return { ...viewport, scale: clampScale(viewport.scale) };
    const scale = clampScale(viewport.scale);
    const width = Math.max(0, finite(size.width, 0));
    const height = Math.max(0, finite(size.height, 0));
    const marginX = Math.max(0, finite(overscroll, 0)) * width;
    const marginY = Math.max(0, finite(overscroll, 0)) * height;
    const x = axisOffset(viewport.x, bounds.minX * scale, bounds.maxX * scale, width, marginX);
    const y = axisOffset(viewport.y, bounds.minY * scale, bounds.maxY * scale, height, marginY);
    return { x, y, scale };
}

function axisOffset(offset: number, low: number, high: number, extent: number, margin: number): number {
    const min = margin - high;
    const max = extent - margin - low;
    return clamp(finite(offset, 0), Math.min(min, max), Math.max(min, max));
}

/** `transform` listo para el atributo SVG. Redondeo a 3 decimales: el DOM no necesita mas y el string se mantiene corto. */
export function toSvgTransform(viewport: Viewport): string {
  const x = Math.round(finite(viewport.x, 0) * 1000) / 1000;
  const y = Math.round(finite(viewport.y, 0) * 1000) / 1000;
  const scale = Math.round(clampScale(viewport.scale) * 1000) / 1000;
  return `translate(${x} ${y}) scale(${scale})`;
}

/** Punto de grafo -> punto de pantalla. */
export function toScreenPoint(viewport: Viewport, point: Point): Point {
  const scale = clampScale(viewport.scale);
  return { x: finite(point.x, 0) * scale + viewport.x, y: finite(point.y, 0) * scale + viewport.y };
}

/** Punto de pantalla -> punto de grafo. La escala se acota antes de dividir, asi que nunca hay division por cero. */
export function toGraphPoint(viewport: Viewport, point: Point): Point {
    const scale = clampScale(viewport.scale);
    return { x: (finite(point.x, 0) - viewport.x) / scale, y: (finite(point.y, 0) - viewport.y) / scale };
}

/** Zoom en porcentaje para el readout accesible (y para el texto del boton). */
export function scalePercent(viewport: Viewport): number {
  return Math.round(clampScale(viewport.scale) * 100);
}

/**
 * Factor de zoom a partir del delta de la rueda (`deltaY` en pixeles).
 *
 * `Math.exp` da un paso constante por pixel, que es lo que se espera de una
 * rueda: un giro completo (~100 px) son algo mas de tres pasos de ZOOM_STEP.
 * El signo del delta decide el sentido (subir = acercar) y el propio
 * `clampScale` de `zoomAtPoint` acota el resultado al rango declarado.
 */
export function wheelToFactor(deltaY: number): number {
  const delta = finite(deltaY, 0);
  if (delta === 0) return 1;
  return Math.exp(-delta * 0.0015);
}

/** Zoom a partir de la distancia entre dos punteros (pellizco), en forma de factor. */
export function pinchToFactor(previousDistance: number, distance: number): number {
  const before = Math.abs(finite(previousDistance, 0));
  const after = Math.abs(finite(distance, 0));
  if (before < EPSILON || after < EPSILON) return 1;
  return after / before;
}