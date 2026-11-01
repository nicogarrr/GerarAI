/**
 * Escala única de notas A+..F para puntuaciones 0-100.
 *
 * Umbrales: 95/90/85/80/75/70/65/60/55/50; por debajo de 50 es F.
 * Módulo puro (sin dependencias): lo usan el scoring avanzado
 * (lib/utils/advancedStockScoring.ts) y el embudo de ProPicks
 * (lib/actions/propicks-funnel.actions.ts) sin arrastrar el grafo
 * de acciones del primero.
 */
export function getGrade(score: number): 'A+' | 'A' | 'A-' | 'B+' | 'B' | 'B-' | 'C+' | 'C' | 'C-' | 'D' | 'F' {
    if (score >= 95) return 'A+';
    if (score >= 90) return 'A';
    if (score >= 85) return 'A-';
    if (score >= 80) return 'B+';
    if (score >= 75) return 'B';
    if (score >= 70) return 'B-';
    if (score >= 65) return 'C+';
    if (score >= 60) return 'C';
    if (score >= 55) return 'C-';
    if (score >= 50) return 'D';
    return 'F';
}
