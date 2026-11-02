/**
 * Veredicto del debate bull/bear al mostrarlo. El juez emite la palabra en
 * inglés («bullish/bearish/neutral», el prompt no cambia) y la sección
 * persistida guarda «VEREDICTO: <palabra> | <frase>»: en castellano salía
 * «veredicto: bullish» y el cuerpo crudo con «VEREDICTO:».
 */
export type DebateVerdict = 'bullish' | 'bearish' | 'neutral';

const VERDICTS: readonly DebateVerdict[] = ['bullish', 'bearish', 'neutral'];

/** La palabra del juez si es una de las tres conocidas; si no, null. */
export function debateVerdict(value: string | null | undefined): DebateVerdict | null {
    const word = (value ?? '').trim().toLowerCase();
    return (VERDICTS as readonly string[]).includes(word) ? (word as DebateVerdict) : null;
}

/** «VEREDICTO: neutral | frase» → { verdict, rationale }; otro texto → null. */
export function parsePersistedVerdict(body: string | null | undefined): { verdict: DebateVerdict; rationale: string } | null {
    const match = /^\s*VEREDICTO:\s*([a-z]+)\s*(?:\|\s*([\s\S]*))?$/i.exec(body ?? '');
    const verdict = match ? debateVerdict(match[1]) : null;
    return verdict ? { verdict, rationale: (match?.[2] ?? '').trim() } : null;
}
