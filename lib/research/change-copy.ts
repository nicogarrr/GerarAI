/** Textos de «Qué ha cambiado» en español y sin repetir el titular en el cuerpo. */
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

export function changeTypeLabel(value: string | null | undefined): string {
    if (!value) return 'N/D';
    return CHANGE_TYPE_LABELS[value] ?? value.replaceAll('_', ' ');
}

const LEGACY_PREFIXES: Array<[RegExp, string]> = [
    [/^Contradictory evidence found for claim:\s*/i, 'La evidencia automática encontró contradicciones con la afirmación: '],
    [/^Evidence classified claim as (\w+):\s*/i, 'La evidencia clasificó la afirmación: '],
];

function normalize(value: string): string {
    return value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

/** Quita frases repetidas y traduce los prefijos antiguos en inglés. */
export function changeSummaryText(summary: string): string {
    let text = (summary ?? '').trim();
    for (const [pattern, replacement] of LEGACY_PREFIXES) text = text.replace(pattern, replacement);
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
