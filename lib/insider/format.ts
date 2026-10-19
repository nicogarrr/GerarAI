/** Formato de operaciones insider (puro, sin imports). */

/** La SEC da «APELLIDO NOMBRE» en mayúsculas: se pasa a «Apellido Nombre». */
export function insiderName(value: string | null | undefined): string {
    const raw = (value ?? '').trim();
    if (!raw) return '—';
    if (raw !== raw.toUpperCase()) return raw;
    return raw
        .toLowerCase()
        .split(/(\s+|\/|-)/)
        .map((part) => (/^[a-zñáéíóúü]/.test(part) ? part[0].toUpperCase() + part.slice(1) : part))
        .join('');
}

const TITLE_ABBREVIATIONS: Array<[RegExp, string]> = [
    [/chief\s+executive(\s+officer)?|\bceo\b/i, 'CEO'],
    [/chief\s+financial(\s+officer)?|\bcfo\b/i, 'CFO'],
    [/chief\s+operating(\s+officer)?|\bcoo\b/i, 'COO'],
    [/chief\s+technology(\s+officer)?|\bcto\b/i, 'CTO'],
];

/** Cargo corto en español a partir del rol y el título que trae el Form 4. */
export function insiderRole(role: string | null | undefined, officerTitle: string | null | undefined): string {
    const title = (officerTitle ?? '').trim();
    const parts: string[] = [];
    const roleText = (role ?? '').toLowerCase();
    if (roleText.includes('multiple insiders')) return 'Varios insiders';
    if (roleText.includes('officer') || title) {
        const abbreviated = TITLE_ABBREVIATIONS.filter(([pattern]) => pattern.test(title)).map(([, label]) => label);
        parts.push(abbreviated.length ? abbreviated.join(' y ') : title || 'Directivo');
    }
    if (roleText.includes('director')) parts.push('Director');
    if (roleText.includes('10% owner')) parts.push('Accionista 10 %');
    return parts.length ? parts.join(' · ') : 'Insider';
}

export function sideLabel(side: string | null | undefined): string {
    return side === 'compra' ? 'Compra' : side === 'venta' ? 'Venta' : '—';
}

/** Codigos de transaccion Form 4 (SEC) en español. P/S tienen su propio
 *  tratamiento (compra/venta); el resto se traduce para no mostrar
 *  «Codigo M» a pelo. Codigo desconocido: se devuelve el codigo tal cual. */
const CODE_LABELS: Record<string, string> = {
    A: 'Concesión',
    C: 'Conversión de derivado',
    D: 'Disposición al emisor',
    E: 'Expiración de derivado',
    F: 'Retención fiscal',
    G: 'Donación',
    H: 'Expiración de derivado',
    I: 'Transacción discrecional',
    J: 'Otra operación',
    K: 'Swap de equity',
    M: 'Ejercicio de opción',
    O: 'Ejercicio de opción',
    U: 'Disposición por OPA',
    W: 'Herencia',
    X: 'Ejercicio de opción',
};

export function insiderCodeLabel(code: string | null | undefined): string {
    const clean = (code ?? '').trim().toUpperCase();
    if (!clean) return '—';
    if (clean === 'P') return sideLabel('compra');
    if (clean === 'S') return sideLabel('venta');
    return CODE_LABELS[clean] ?? `Código ${clean}`;
}

/** El Form 4 aplana las personas declarantes; los filtros institucionales
 *  (Berkshire Hathaway Inc, fondos) no son «insiders» personales. Detecta el
 *  nombre de entidad para etiquetarlo en la interfaz en vez de mezclarlo. */
const ENTITY_SUFFIX = /\b(inc|corp|corporation|llc|l\.l\.c|lp|l\.p|ltd|plc|s\.a|partners|capital|fund|holdings|management|advisors?|trust|group)\b\.?/i;

export function isInstitutionalInsiderName(name: string | null | undefined): boolean {
    return ENTITY_SUFFIX.test((name ?? '').trim());
}

/** Claves de señal del monitor -> etiqueta visible (Tester 6 barrido).
 *  La clave es el identificador estable del backend; lo que se muestra es la
 *  etiqueta. Clave nueva desconocida: se muestra cruda (honesta), nunca
 *  se inventa una lectura. */
const SIGNAL_LABELS: Record<string, string> = {
    cluster_buy: 'Cluster de compra',
    c_suite_buy: 'Compra de CEO/CFO',
    big_buy: 'Gran compra',
};

export function signalLabel(signal: string | null | undefined): string {
    const key = (signal ?? '').trim();
    if (!key) return '—';
    return SIGNAL_LABELS[key] ?? key;
}

/** Tooltip con el umbral REAL del backend (insider_service.py): el guard lo
 *  fija contra la fuente. big_buy es estrictamente mayor que 1 M$ (>), así
 *  que «supera», no «≥». Nunca afirma «mercado abierto»: el código P no
 *  siempre lo distingue (docstring del backend). Clave desconocida: sin
 *  tooltip, no se inventa umbral. */
const SIGNAL_TOOLTIPS: Record<string, string> = {
    cluster_buy: '3 o más insiders distintos compran en 30 días',
    c_suite_buy: 'El CEO o el CFO compra acciones',
    big_buy: 'Una compra supera 1 M$',
};

export function signalTooltip(signal: string | null | undefined): string | undefined {
    const key = (signal ?? '').trim();
    if (!key) return undefined;
    return SIGNAL_TOOLTIPS[key];
}
