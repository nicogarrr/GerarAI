/** Turnos previos que viajan con la pregunta del Cerebro: acotados, solo texto. */
export type BrainHistoryTurn = { role: 'user' | 'assistant'; content: string };

export function trimBrainHistory(history?: BrainHistoryTurn[] | null): BrainHistoryTurn[] {
    return (history ?? [])
        .filter((turn) => (turn.role === 'user' || turn.role === 'assistant') && turn.content.trim())
        .slice(-6)
        .map((turn) => ({ role: turn.role, content: turn.content.slice(0, 1500) }));
}
