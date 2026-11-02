/** Textos de «Qué ha cambiado» en el idioma elegido y sin repetir el titular en el cuerpo. */
// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';

const CHANGE_TYPE_LABELS: Record<string, string> = {
    update: 'actualización',
    earnings_update: 'resultados',
    news_material_update: 'noticia material',
    news_potential_invalidation: 'posible invalidación',
    news_material_positive: 'noticia positiva',
    claim_contradiction: 'afirmación contradicha',
    claim_superseded: 'afirmación superada',
    claim_stale: 'afirmación desactualizada',
    claim_uncertain: 'afirmación incierta',
};

const CHANGE_TYPE_LABELS_EN: Record<string, string> = {
    update: 'update',
    earnings_update: 'earnings',
    news_material_update: 'material news',
    news_potential_invalidation: 'possible invalidation',
    news_material_positive: 'positive news',
    claim_contradiction: 'contradicted claim',
    claim_superseded: 'superseded claim',
    claim_stale: 'outdated claim',
    claim_uncertain: 'uncertain claim',
};

export function changeTypeLabel(value: string | null | undefined, locale: 'es' | 'en' = 'es'): string {
    if (!value) return locale === 'en' ? '—' : 'N/D';
    const table = locale === 'en' ? CHANGE_TYPE_LABELS_EN : CHANGE_TYPE_LABELS;
    return table[value] ?? value.replaceAll('_', ' ');
}

const LEGACY_PREFIXES: Array<[RegExp, string]> = [
    [/No stored thesis is available for semantic impact mapping\./g, 'No hay una tesis guardada para evaluar el impacto.'],
    [/No structural thesis node matched with sufficient confidence\./g, 'No se ha encontrado una relación suficientemente fiable con la tesis.'],
    [/Affects (\d+) claims and thesis nodes:\s*/g, 'Afecta a $1 afirmaciones y a estos apartados de la tesis: '],
    // Forma antigua en español persistida por el backend («y nodos de la tesis»):
    // con 0 afirmaciones se leía como si nada estuviera afectado pese a listar
    // apartados. Se reescribe a la forma honesta y traducible de etiquetas.
    [/Afecta a 0 afirmaciones y nodos de la tesis:\s*/g, 'No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: '],
    [/Afecta a (\d+) afirmaciones y nodos de la tesis:\s*/g, 'Afecta a $1 afirmaciones y a estos apartados de la tesis: '],
    [/^Contradictory evidence found for claim:\s*/i, 'La evidencia automática encontró contradicciones con la afirmación: '],
    [/^Evidence classified claim as (\w+):\s*/i, 'La evidencia clasificó la afirmación: '],
];

function normalize(value: string): string {
    return value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

/**
 * Con Ajustes → Idioma en inglés: los prefijos del backend (antiguos en inglés
 * y actuales en español) salen en inglés. Antes se pasaban siempre a español.
 */
const NO_STORED_THESIS = /No stored thesis is available for semantic impact mapping\.|No hay una tesis guardada para evaluar el impacto\./g;
const NO_NODE_MATCHED = /No structural thesis node matched with sufficient confidence\.|No se ha encontrado una relación suficientemente fiable con la tesis\./g;
const AFFECTS_AREAS =
    /(?:Affects (\d+) claims and thesis nodes|Afecta a (\d+) afirmaciones y (?:a estos apartados|nodos) de la tesis|No afecta a ninguna afirmación concreta; toca estos apartados de la tesis):\s*([^.!?]*)/g;

const SPANISH_NODE_TO_EN: Record<string, string> = {
    Tecnología: 'Technology', Financiación: 'Funding', Comercialización: 'Commercialization',
    Ejecución: 'Execution', Regulación: 'Regulatory', 'Economía del negocio': 'Economics', 'Ventaja competitiva': 'Moat',
};

function englishSummary(text: string): string {
    const t = createTranslator('en');
    return text
        .replace(NO_STORED_THESIS, t('research.changeCopy.noStoredThesis'))
        .replace(NO_NODE_MATCHED, t('research.changeCopy.noNodeMatched'))
        .replace(AFFECTS_AREAS, (_match: string, en?: string, es?: string, labels: string = '') => {
            const count = Number(en ?? es ?? 0);
            const areas = labels.split(', ').filter(Boolean).map((label: string) => SPANISH_NODE_TO_EN[label] ?? label).join(', ');
            if (count === 1) return t('research.changeCopy.affectsOneClaim', { areas });
            return count > 0
                ? t('research.changeCopy.affectsClaims', { count: String(count), areas })
                : t('research.changeCopy.affectsNoClaim', { areas });
        });
}

function dedupeSentences(text: string): string {
    const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
    const seen: string[] = [];
    const kept = sentences.filter((sentence) => {
        const key = normalize(sentence.replace(/^[^:]{0,80}:\s*/, ''));
        if (!key) return true;
        if (seen.some((prior) => prior === key || (key.length > 24 && (prior.includes(key) || key.includes(prior))))) return false;
        seen.push(key);
        return true;
    });
    return kept.join(' ');
}

/** Quita frases repetidas y traduce los prefijos antiguos al idioma elegido (español por defecto). */
export function changeSummaryText(summary: string, locale: 'es' | 'en' = 'es'): string {
    let text = (summary ?? '').trim();
    if (locale === 'en') return dedupeSentences(englishSummary(text));
    for (const [pattern, replacement] of LEGACY_PREFIXES) text = text.replace(pattern, replacement);
    return dedupeSentences(text).replace(/((?:Afecta a \d+ afirmaciones y a|No afecta a ninguna afirmación concreta; toca) estos apartados de la tesis: )([^.!?]+)/g, (_, prefix: string, labels: string) => {
        const nodes: Record<string, string> = {
            Technology: 'Tecnología', Funding: 'Financiación', Commercialization: 'Comercialización',
            Execution: 'Ejecución', Regulatory: 'Regulación', Economics: 'Economía del negocio', Moat: 'Ventaja competitiva',
        };
        return prefix + labels.split(', ').map((label) => nodes[label] ?? label).join(', ');
    });
}

/** Avisos fijos que el backend añade a las noticias seguidas, en los dos idiomas en que los guarda. */
const NEWS_NOTES: Array<{ es: string; en: string }> = [
    {
        es: 'Revisa la fuente; la fecha de GDELT no es la fecha de publicación y el titular no confirma por sí solo los hechos.',
        en: 'Check the source; the GDELT date is not the publication date and the headline alone does not confirm the facts.',
    },
    { es: 'Revisa la fuente; el titular no confirma por sí solo los hechos.', en: 'Check the source; the headline alone does not confirm the facts.' },
    {
        es: 'Señal de vigilancia: si SpaceX cierra acuerdos con operadoras grandes, el argumento de que el foso de AST son sus acuerdos con operadoras se debilita.',
        en: "Watch signal: if SpaceX closes deals with large carriers, the argument that AST's moat is its carrier agreements weakens.",
    },
];

function localizedNewsNotes(text: string, locale: 'es' | 'en'): string {
    let out = text;
    for (const note of NEWS_NOTES) out = out.split(locale === 'en' ? note.es : note.en).join(locale === 'en' ? note.en : note.es);
    return out;
}

/** Render old persisted wrappers without changing the original evidence. */
export function changeHeadlineCopy(summary: string, locale: 'es' | 'en' = 'es'): { text: string; note: string | null } {
    let text = localizedNewsNotes((summary ?? '').trim(), locale);
    text = text.replace(/^Noticia material que requiere revisión de la tesis:\s*/i, '');
    // La fecha llega en ISO (avisos antiguos) o legible: «27 sept 2026» / «Sep 27, 2026».
    const day = String.raw`(?:\d{4}-\d{2}-\d{2}|\d{1,2} [a-z]{3,4}\.? \d{4}|[A-Z][a-z]{2} \d{1,2}, \d{4})`;
    text = text.replace(new RegExp(String.raw`^Artículo de [\s\S]*?,\s*(?:fechad[ao] el ${day} por [^:]+|detectad[ao] por GDELT el ${day}):\s*`, 'i'), '');
    text = text.replace(new RegExp(String.raw`^Article from [\s\S]*?,\s*(?:dated ${day} by [^:]+|detected by GDELT on ${day}):\s*`, 'i'), '');
    const warning = text.search(/(?:Revisa la fuente;\s*(?:la fecha de GDELT|el titular no confirma)|Check the source;\s*the (?:GDELT date|headline alone))/i);
    const note = warning >= 0 ? text.slice(warning).trim() : null;
    if (warning >= 0) text = text.slice(0, warning).trim();
    return { text: changeSummaryText(text, locale), note };
}
