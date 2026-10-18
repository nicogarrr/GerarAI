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
