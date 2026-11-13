import type { TranslateFn } from '@/lib/i18n/translate';

// Textos visibles en los diccionarios (patrón flow-text): import relativo con
// atributo por los tests con node --experimental-strip-types. Las funciones
// siguen siendo puras: solo leen datos, sin dependencia de React.
import esInsider from '../i18n/messages/es/insider.json' with { type: 'json' };
import enInsider from '../i18n/messages/en/insider.json' with { type: 'json' };

/** Formato de operaciones insider (puro; solo importa el tipo TranslateFn). */

// Uso por literal para el guard de i18n (claves consumidas por objeto).
export const INSIDER_FORMAT_KEY_LITERALS = [
    'insider.feed.roleTitles.chiefExecutive',
    'insider.feed.roleTitles.chiefFinancial',
    'insider.feed.roleTitles.chiefOperating',
    'insider.feed.roleTitles.chiefTechnology',
    'insider.feed.roleTitles.chiefLegal',
    'insider.feed.roleTitles.generalCounsel',
    'insider.feed.roleTitles.chiefAccounting',
    'insider.feed.roleTitles.chiefCommercial',
    'insider.feed.roleTitles.chiefMedical',
    'insider.feed.roleTitles.chiefInformation',
    'insider.feed.roleTitles.chiefHumanResources',
    'insider.feed.roleTitles.chiefStrategy',
    'insider.feed.roleTitles.chiefInvestment',
    'insider.feed.roleTitles.chiefMarketing',
    'insider.feed.roleTitles.chiefRevenue',
    'insider.feed.roleTitles.chiefProduct',
    'insider.feed.roleTitles.chiefRisk',
    'insider.feed.roleTitles.chiefCompliance',
    'insider.feed.roleTitles.chiefData',
    'insider.feed.roleTitles.seniorVicePresident',
    'insider.feed.roleTitles.executiveVicePresident',
    'insider.feed.roleTitles.vicePresident',
    'insider.feed.roleTitles.executiveChair',
    'insider.feed.roleTitles.chair',
    'insider.feed.roleTitles.president',
    'insider.feed.roleTitles.governmentAffairs',
    'insider.feed.roleTitles.officer',
    'insider.feed.roleTitles.treasurer',
    'insider.feed.roleTitles.secretary',
    'insider.feed.roleParts.multipleInsiders',
    'insider.feed.roleParts.director',
    'insider.feed.roleParts.owner10',
    'insider.feed.roleParts.insider',
    'insider.feed.signalLabels.cluster_buy',
    'insider.feed.signalLabels.c_suite_buy',
    'insider.feed.signalLabels.big_buy',
    'insider.feed.signalTooltips.cluster_buy',
    'insider.feed.signalTooltips.c_suite_buy',
    'insider.feed.signalTooltips.big_buy',
] as const;

const ES_TITLES = esInsider.feed.roleTitles;
const ES_PARTS = esInsider.feed.roleParts;
const EN_TITLES = enInsider.feed.roleTitles;
const EN_PARTS = enInsider.feed.roleParts;

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
 * - Las etiquetas viven en los diccionarios (insider.feed.roleTitles).
 */
const TITLE_ABBREVIATIONS: Array<[RegExp, string]> = [
    [/chief\s+executive(\s+officer)?|\bceo\b/i, ES_TITLES.chiefExecutive],
    [/chief\s+financial(\s+officer)?|\bcfo\b/i, ES_TITLES.chiefFinancial],
    [/chief\s+operating(\s+officer)?|\bcoo\b/i, ES_TITLES.chiefOperating],
    [/chief\s+technology(\s+officer)?|\bcto\b/i, ES_TITLES.chiefTechnology],
    [/chief\s+legal(\s+officer)?/i, ES_TITLES.chiefLegal],
    [/general\s+counsel|\bgc\b/i, ES_TITLES.generalCounsel],
    [/chief\s+accounting(\s+officer)?/i, ES_TITLES.chiefAccounting],
    [/chief\s+commercial(\s+officer)?/i, ES_TITLES.chiefCommercial],
    [/chief\s+medical(\s+officer)?/i, ES_TITLES.chiefMedical],
    [/chief\s+information(\s+officer)?/i, ES_TITLES.chiefInformation],
    [/chief\s+(human\s+resources|people)(\s+officer)?|\bchro\b/i, ES_TITLES.chiefHumanResources],
    [/chief\s+strategy(\s+officer)?/i, ES_TITLES.chiefStrategy],
    [/chief\s+investment(\s+officer)?/i, ES_TITLES.chiefInvestment],
    [/chief\s+marketing(\s+officer)?/i, ES_TITLES.chiefMarketing],
    [/chief\s+revenue(\s+officer)?/i, ES_TITLES.chiefRevenue],
    [/chief\s+product(\s+officer)?/i, ES_TITLES.chiefProduct],
    [/chief\s+risk(\s+officer)?/i, ES_TITLES.chiefRisk],
    [/chief\s+compliance(\s+officer)?/i, ES_TITLES.chiefCompliance],
    [/chief\s+data(\s+officer)?/i, ES_TITLES.chiefData],
    [/senior\s+vice\s+president|\bsvp\b/i, ES_TITLES.seniorVicePresident],
    [/executive\s+vice\s+president|\bevp\b/i, ES_TITLES.executiveVicePresident],
    [/vice\s+president|\bvp\b/i, ES_TITLES.vicePresident],
    // Después de los VP: «Vice President» ya se consumió arriba y no llega
    // aquí como «Presidente»; un «President» suelto sí. Los calificadores
    // (Assistant, Co-, «of ...», divisiones) hacen saltar el consumo total
    // y devuelven el título original, así que no rebajan el cargo.
    // «Vice Chair» / «Co-Chair» dejan resto sin mapear y se muestran tal cual.
    [/executive\s+chair(man|woman|person)?/i, ES_TITLES.executiveChair],
    [/\bchair(man|woman|person)?\b/i, ES_TITLES.chair],
    [/president/i, ES_TITLES.president],
    [/government\s+affairs/i, ES_TITLES.governmentAffairs],
    [/^officer$/i, ES_TITLES.officer],
    [/treasurer/i, ES_TITLES.treasurer],
    [/secretary/i, ES_TITLES.secretary],
];

/** Conectores entre cargos compuestos: no son «resto sin mapear». */
const CONNECTORS = /\b(and|y)\b/gi;

/** Cargo corto en español a partir del rol y el título que trae el Form 4. */
/** Cargo en inglés: el título de la SEC ya llega en inglés y se muestra tal cual. */
function insiderRoleEn(roleText: string, title: string): string {
    if (roleText.includes('multiple insiders')) return EN_PARTS.multipleInsiders;
    const parts: string[] = [];
    if (roleText.includes('officer') || title) parts.push(title || EN_TITLES.officer);
    if (roleText.includes('director')) parts.push(EN_PARTS.director);
    if (roleText.includes('10% owner')) parts.push(EN_PARTS.owner10);
    return parts.length ? parts.join(' · ') : EN_PARTS.insider;
}

export function insiderRole(
    role: string | null | undefined,
    officerTitle: string | null | undefined,
    locale: 'es' | 'en' = 'es',
): string {
    const title = (officerTitle ?? '').trim();
    const parts: string[] = [];
    const roleText = (role ?? '').toLowerCase();
    if (locale === 'en') return insiderRoleEn(roleText, title);
    if (roleText.includes('multiple insiders')) return ES_PARTS.multipleInsiders;
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
        parts.push(matched.length ? matched.map((m) => m.label).join(' y ') : title || ES_TITLES.officer);
    }
    if (roleText.includes('director')) parts.push(ES_PARTS.director);
    if (roleText.includes('10% owner')) parts.push(ES_PARTS.owner10);
    return parts.length ? parts.join(' · ') : ES_PARTS.insider;
}

export function sideLabel(side: string | null | undefined, t?: TranslateFn): string {
    if (t) {
        return side === 'compra'
            ? t('insider.feed.sideBuyLabel')
            : side === 'venta'
              ? t('insider.feed.sideSellLabel')
              : '—';
    }
    // Sin t: diccionario es directo (scripts y llamadas legacy fuera de React).
    return side === 'compra' ? esInsider.feed.sideBuyLabel : side === 'venta' ? esInsider.feed.sideSellLabel : '—';
}

/** Codigos de transaccion Form 4 (SEC) en español. P/S tienen su propio
 *  tratamiento (compra/venta); el resto se traduce para no mostrar
 *  «Codigo M» a pelo. Codigo desconocido: se devuelve el codigo tal cual.
 *  Etiquetas en insider.feed.codeLabels del diccionario es. */
const CODE_LABELS: Record<string, string> = {
    A: esInsider.feed.codeLabels.A,
    C: esInsider.feed.codeLabels.C,
    D: esInsider.feed.codeLabels.D,
    E: esInsider.feed.codeLabels.E,
    F: esInsider.feed.codeLabels.F,
    G: esInsider.feed.codeLabels.G,
    H: esInsider.feed.codeLabels.H,
    I: esInsider.feed.codeLabels.I,
    J: esInsider.feed.codeLabels.J,
    K: esInsider.feed.codeLabels.K,
    M: esInsider.feed.codeLabels.M,
    O: esInsider.feed.codeLabels.O,
    U: esInsider.feed.codeLabels.U,
    W: esInsider.feed.codeLabels.W,
    X: esInsider.feed.codeLabels.X,
};

/** Claves i18n de los códigos conocidos, como literales para que el chequeo
 *  i18n las vea referenciadas y TranslationKey las acepte. */
const CODE_KEYS: Record<string, Parameters<TranslateFn>[0]> = {
    A: 'insider.feed.codeLabels.A',
    C: 'insider.feed.codeLabels.C',
    D: 'insider.feed.codeLabels.D',
    E: 'insider.feed.codeLabels.E',
    F: 'insider.feed.codeLabels.F',
    G: 'insider.feed.codeLabels.G',
    H: 'insider.feed.codeLabels.H',
    I: 'insider.feed.codeLabels.I',
    J: 'insider.feed.codeLabels.J',
    K: 'insider.feed.codeLabels.K',
    M: 'insider.feed.codeLabels.M',
    O: 'insider.feed.codeLabels.O',
    U: 'insider.feed.codeLabels.U',
    W: 'insider.feed.codeLabels.W',
    X: 'insider.feed.codeLabels.X',
};

export function insiderCodeLabel(code: string | null | undefined, t?: TranslateFn): string {
    const clean = (code ?? '').trim().toUpperCase();
    if (!clean) return '—';
    if (clean === 'P') return sideLabel('compra', t);
    if (clean === 'S') return sideLabel('venta', t);
    if (t) {
        const key = CODE_KEYS[clean];
        return key ? t(key) : t('insider.feed.codeUnknown', { code: clean });
    }
    // Sin t: diccionario es directo (scripts y llamadas legacy fuera de React).
    return CODE_LABELS[clean] ?? esInsider.feed.codeUnknown.replace('{code}', clean);
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
 *  etiqueta (insider.feed.signalLabels). Clave nueva desconocida: se muestra
 *  cruda (honesta), nunca se inventa una lectura. */
export function signalLabel(signal: string | null | undefined, locale: 'es' | 'en' = 'es'): string {
    const key = (signal ?? '').trim();
    if (!key) return '—';
    const labels: Record<string, string> = locale === 'en' ? enInsider.feed.signalLabels : esInsider.feed.signalLabels;
    return labels[key] ?? key;
}

/** Tooltip con el umbral REAL del backend (insider_service.py): el guard lo
 *  fija contra la fuente. big_buy es estrictamente mayor que 1 M$ (>), así
 *  que «supera», no «≥». Nunca afirma «mercado abierto»: el código P no
 *  siempre lo distingue (docstring del backend). Clave desconocida: sin
 *  tooltip, no se inventa umbral. Textos en insider.feed.signalTooltips. */
export function signalTooltip(signal: string | null | undefined, locale: 'es' | 'en' = 'es'): string | undefined {
    const key = (signal ?? '').trim();
    if (!key) return undefined;
    const tooltips: Record<string, string> = locale === 'en' ? enInsider.feed.signalTooltips : esInsider.feed.signalTooltips;
    return tooltips[key];
}
