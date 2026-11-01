import { describe, expect, it } from 'vitest';
import { getGrade } from '@/lib/utils/advancedStockScoring';

// Escala única A+..F usada por el scoring avanzado y por el embudo de ProPicks.
// Umbrales: 95/90/85/80/75/70/65/60/55/50; por debajo de 50 es F.
describe('getGrade (escala única A+..F)', () => {
    it.each([
        [100, 'A+'],
        [95, 'A+'],
        [94.9, 'A'],
        [90, 'A'],
        [85, 'A-'],
        [80, 'B+'],
        [75, 'B'],
        [70, 'B-'],
        [65, 'C+'],
        [60, 'C'],
        [55, 'C-'],
        [50, 'D'],
        [49.9, 'F'],
        [0, 'F'],
    ] as const)('puntuación %s -> %s', (score, grade) => {
        expect(getGrade(score)).toBe(grade);
    });
});
