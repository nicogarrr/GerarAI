/**
 * Fecha del evento en el flujo de noticias: un día sin hora real debe pintarse
 * en es-ES («27 oct 2026»), nunca como ISO crudo («2026-10-27»), y sin
 * desplazarse de día por la zona horaria (día de calendario literal).
 */
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/ui/empty-state', () => ({}));
vi.mock('@/components/common/TickerContextBadges', () => ({}));
vi.mock('@/components/research/NewsHeadline', () => ({}));
vi.mock('@/components/research/NewsSecondOrder', () => ({}));
vi.mock('@/components/research/NewsSummary', () => ({}));

import { eventDateText } from '@/components/research/NewsEventsFlow';

describe('eventDateText', () => {
    it('solo fecha (sin T): «27 oct 2026», no ISO', () => {
        expect(eventDateText('2026-10-27')).toBe('27 oct 2026');
    });
    it('medianoche UTC por defecto: solo el día, en es-ES', () => {
        expect(eventDateText('2026-10-27T00:00:00Z')).toBe('27 oct 2026');
    });
    it('con hora real: fecha y hora de usuario', () => {
        const text = eventDateText('2026-10-27T14:35:00Z');
        expect(text).toContain('2026');
        expect(text).not.toBe('2026-10-27');
    });
});
