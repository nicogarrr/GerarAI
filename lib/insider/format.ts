import type { TranslateFn } from '@/lib/i18n/translate';

/** Formato de operaciones insider (puro; solo importa el tipo TranslateFn). */

/** La SEC da «APELLIDO NOMBRE» en mayúsculas: se pasa a «Apellido Nombre». */
export function insiderName(value: string | null | undefined): string {
    const raw = (value ?? '').trim();
    if (!raw) return '—';
    if (raw !== raw.toUpperCase()) return raw;
    return raw
        .toLowerCase()
        .split(/(\s+|\/|-|'|’)/)
        .map((part) => (/^[a-zñáéíóúü]/.test(part) ? part[0].toUpperCase() + part.slice(1) : part))
        .join('');
}

/**
 * Cargos Form 4 más comunes -> español (mapa fijo y revisable, Tester 6).
 *
 * Reglas de veracidad (auditor 2026-10-19):
 * - Siglas con una sola lectura segura: CEO, CFO, COO, CTO, GC, EVP, SVP, VP,
 *   CHRO. Las ambiguas (CRO ingresos/riesgos, CCO comercial/cumplimiento, CIO
 *   sistemas/inversiones, CSO estrategia/seguridad, CLO legal/lending, CMO
 *   medico/marketing...) NO se traducen por sigla: solo por el titulo
 *   deletreado («Chief Risk Officer» sí; «CRO» se queda crudo).
 * - Consumo total: el título traducido debe quedar COMPLETAMENTE cubierto por
 *   los patrones; si queda resto alfabético sin mapear (divisiones, «Global
 *   Sales», «Assistant», «Co-», «of ...»), se muestra el título original.
 *   Nunca se rebaja un cargo: «Assistant Secretary» no es «Secretario».
 * - Orden de específico a genérico: cada patrón consume su trozo antes de
 *   probar el siguiente («Senior Vice President» no dispara también
 *   «Vicepresidente» ni «Presidente»).
 * - Lo no mapeado se muestra tal cual: nunca se traduce por inferencia.
 */
const TITLE_ABBREVIATIONS: Array<[RegExp, string]> = [
    [/chief\s+executive(\s+officer)?|\bceo\b/i, 'CEO'],
    [/chief\s+financial(\s+officer)?|\bcfo\b/i, 'CFO'],
    [/chief\s+operating(\s+officer)?|\bcoo\b/i, 'COO'],
    [/chief\s+technology(\s+officer)?|\bcto\b/i, 'CTO'],
    [/chief\s+legal(\s+officer)?/i, 'Director jurídico'],
    [/general\s+counsel|\bgc\b/i, 'Asesor jurídico general'],
    [/chief\s+accounting(\s+officer)?/i, 'Director de contabilidad'],
    [/chief\s+commercial(\s+officer)?/i, 'Director comercial'],
    [/chief\s+medical(\s+officer)?/i, 'Director médico'],
    [/chief\s+information(\s+officer)?/i, 'Director de sistemas de información'],
    [/chief\s+(human\s+resources|people)(\s+officer)?|\bchro\b/i, 'Director de recursos humanos'],
    [/chief\s+strategy(\s+officer)?/i, 'Director de estrategia'],
    [/chief\s+investment(\s+officer)?/i, 'Director de inversiones'],
    [/chief\s+marketing(\s+officer)?/i, 'Director de marketing'],
    [/chief\s+revenue(\s+officer)?/i, 'Director de ingresos'],
    [/chief\s+product(\s+officer)?/i, 'Director de producto'],
    [/chief\s+risk(\s+officer)?/i, 'Director de riesgos'],
    [/chief\s+compliance(\s+officer)?/i, 'Director de cumplimiento'],
    [/chief\s+data(\s+officer)?/i, 'Director de datos'],
    [/senior\s+vice\s+president|\bsvp\b/i, 'Vicepresidente senior'],
    [/executive\s+vice\s+president|\bevp\b/i, 'Vicepresidente ejecutivo'],
    [/vice\s+president|\bvp\b/i, 'Vicepresidente'],
    // Después de los VP: «Vice President» ya se consumió arriba y no llega
    // aquí como «Presidente»; un «President» suelto sí. Los calificadores
    // (Assistant, Co-, «of ...», divisiones) hacen saltar el consumo total
    // y devuelven el título original, así que no rebajan el cargo.
    // «Vice Chair» / «Co-Chair» dejan resto sin mapear y se muestran tal cual.
    [/executive\s+chair(man|woman|person)?/i, 'Presidente ejecutivo'],
    [/\bchair(man|woman|person)?\b/i, 'Presidente del consejo'],
    [/president/i, 'Presidente'],
    [/government\s+affairs/i, 'Relaciones gubernamentales'],
    [/^officer$/i, 'Directivo'],
    [/treasurer/i, 'Tesorero'],
    [/secretary/i, 'Secretario'],
];

/** Conectores entre cargos compuestos: no son «resto sin mapear». */
const CONNECTORS = /\b(and|y)\b/gi;

/** Cargo corto en español a partir del rol y el título que trae el Form 4. */
export function insiderRole(role: string | null | undefined, officerTitle: string | null | undefined): string {
    const title = (officerTitle ?? '').trim();
    const parts: string[] = [];
    const roleText = (role ?? '').toLowerCase();
    if (roleText.includes('multiple insiders')) return 'Varios insiders';
    if (roleText.includes('officer') || title) {
        // Cada patrón consume su trozo antes de probar el siguiente. Si al
        // final queda texto alfabético (algo sin mapear: división, área,
        // «Assistant»...), la traducción parcial perdería información y
        // rebajaría o inventaría el cargo: se muestra el título original.
        let rest = title;
        const matched: Array<{ at: number; label: string }> = [];
        for (const [pattern, label] of TITLE_ABBREVIATIONS) {
            if (pattern.test(rest)) {
                const at = title.search(pattern);
                matched.push({ at: at < 0 ? Number.MAX_SAFE_INTEGER : at, label });
                rest = rest.replace(pattern, ' ');
            }
        }
        const leftover = rest.replace(CONNECTORS, ' ').replace(/[^a-zñáéíóúü]/gi, '');
        if (leftover.length > 0) matched.length = 0;
        matched.sort((a, b) => a.at - b.at);
        parts.push(matched.length ? matched.map((m) => m.label).join(' y ') : title || 'Directivo');
    }
    if (roleText.includes('director')) parts.push('Director');
    if (roleText.includes('10% owner')) parts.push('Accionista 10 %');
    return parts.length ? parts.join(' · ') : 'Insider';
}

export function sideLabel(side: string | null | undefined, t?: TranslateFn): string {
    if (t) {
        return side === 'compra'
            ? t('insider.feed.sideBuyLabel')
            : side === 'venta'
              ? t('insider.feed.sideSellLabel')
              : '—';
    }
    // Sin t: literales historicos es (scripts y llamadas legacy fuera de React).
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

export function insiderCodeLabel(code: string | null | undefined, t?: TranslateFn): string {
    const clean = (code ?? '').trim().toUpperCase();
    if (!clean) return '—';
    if (clean === 'P') return sideLabel('compra', t);
    if (clean === 'S') return sideLabel('venta', t);
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
