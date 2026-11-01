import { describe, expect, it } from 'vitest';
import { changeHeadlineCopy, changeSummaryText, changeTypeLabel } from '@/lib/research/change-copy';

describe('changeTypeLabel', () => {
    it('vacío -> N/D; conocido en español; desconocido humanizado', () => {
        expect(changeTypeLabel(null)).toBe('N/D');
        expect(changeTypeLabel('')).toBe('N/D');
        expect(changeTypeLabel('earnings_update')).toBe('resultados');
        expect(changeTypeLabel('some_new_type')).toBe('some new type');
    });
});

describe('changeSummaryText', () => {
    it('traduce prefijos heredados en inglés', () => {
        expect(changeSummaryText('No stored thesis is available for semantic impact mapping.')).toBe('No hay una tesis guardada para evaluar el impacto.');
        expect(changeSummaryText('Contradictory evidence found for claim: ventas suben')).toBe('La evidencia automática encontró contradicciones con la afirmación: ventas suben');
    });
    it('"Affects N claims" se traduce y los apartados de la tesis también', () => {
        expect(changeSummaryText('Affects 3 claims and thesis nodes: Technology, Moat')).toBe('Afecta a 3 afirmaciones y a estos apartados de la tesis: Tecnología, Ventaja competitiva');
    });
    it('0 afirmaciones se redacta como "no afecta a ninguna"', () => {
        expect(changeSummaryText('Afecta a 0 afirmaciones y nodos de la tesis: Funding')).toBe('No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: Financiación');
    });
    it('apartado desconocido se deja como llega', () => {
        expect(changeSummaryText('Afecta a 2 afirmaciones y nodos de la tesis: Otro')).toContain('Otro');
    });
    it('elimina frases repetidas (misma frase tras el prefijo, sin importar puntuación)', () => {
        const out = changeSummaryText('Resumen: Los ingresos suben un 5 %. Otro: los ingresos suben un 5 %! Distinta.');
        expect(out.match(/ingresos suben/gi)).toHaveLength(1);
        expect(out).toContain('Distinta.');
    });
    it('frases cortas iguales distintas no se funden por inclusión; las largas contenidas sí', () => {
        expect(changeSummaryText('Sube. Sube más.')).toBe('Sube. Sube más.');
        const long = 'Los ingresos del trimestre superan claramente lo previsto por la directiva.';
        expect(changeSummaryText(`${long} Notas: ${long.slice(0, -1)} y más.`)).toBe(long);
    });
    it('nulo/vacío no rompe', () => {
        expect(changeSummaryText('')).toBe('');
        expect(changeSummaryText(undefined as unknown as string)).toBe('');
    });
});

describe('changeSummaryText con el inglés elegido', () => {
    it('no pasa a español el texto del backend', () => {
        expect(changeSummaryText('No stored thesis is available for semantic impact mapping.', 'en')).toBe('There is no saved thesis to assess the impact against.');
        expect(changeSummaryText('News. Affects 2 claims and thesis nodes: Funding.', 'en')).toBe('News. Affects 2 claims and these areas of the thesis: Funding.');
        expect(changeSummaryText('Noticia. Afecta a 1 afirmaciones y a estos apartados de la tesis: Moat.', 'en')).toBe('Noticia. Affects 1 claim and these areas of the thesis: Moat.');
        expect(changeHeadlineCopy('Noticia material que requiere revisión de la tesis: Acme wins a contract.', 'en').text).toBe('Acme wins a contract.');
        expect(changeSummaryText('No stored thesis is available for semantic impact mapping.')).toBe('No hay una tesis guardada para evaluar el impacto.');
    });
});
