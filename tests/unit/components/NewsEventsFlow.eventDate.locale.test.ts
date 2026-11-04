/**
 * Fecha del evento con la app en inglés: si la hora de la fuente no se puede
 * formatear, eventDateText cae al día. Antes comparaba con el «N/D» fijo en
 * castellano y, en inglés (donde el formateador devuelve «N/A»), pintaba «N/A»
 * en vez de la fecha.
 */
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/ui/empty-state', () => ({}));
vi.mock('@/components/common/TickerContextBadges', () => ({}));
vi.mock('@/components/research/NewsHeadline', () => ({}));
vi.mock('@/components/research/NewsSecondOrder', () => ({}));
vi.mock('@/components/research/NewsSummary', () => ({}));

import { eventDateText } from '@/components/research/NewsEventsFlow';

describe('eventDateText con el idioma activo', () => {
    it('hora ilegible en inglés: el día en inglés, no «N/A»', () => {
        const text = eventDateText('2026-10-27T25:61:00Z', 'en');
        expect(text).not.toBe('N/A');
        expect(text).toContain('2026');
        expect(text).toMatch(/Oct/);
    });
    it('hora ilegible en castellano: el día en castellano, como siempre', () => {
        expect(eventDateText('2026-10-27T25:61:00Z', 'es')).toBe('27 oct 2026');
    });
});
