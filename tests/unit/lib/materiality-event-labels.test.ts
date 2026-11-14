import { describe, expect, it } from 'vitest';
import { etiquetaTipoEvento } from '@/lib/labels';
import es from '@/lib/i18n/messages/es/labels.json';
import en from '@/lib/i18n/messages/en/labels.json';

// Backend's MATERIAL_KEYWORDS plus its general_news fallback. Python checks
// these keys against both catalogs; this checks the public mapper uses them.
const eventTypes = ['capital_allocation', 'contract', 'dilution', 'earnings', 'regulatory', 'general_news'] as const;

describe('materiality event labels reach the UI', () => {
    for (const locale of ['es', 'en'] as const) {
        it.each(eventTypes)(`translates %s in ${locale} instead of leaking a backend code`, (eventType) => {
            const translation = (locale === 'es' ? es : en).eventTypes[eventType];
            expect(translation).toEqual(expect.any(String));
            expect(translation.trim()).not.toBe('');
            expect(translation).not.toBe(eventType);
            expect(etiquetaTipoEvento(eventType, locale)).toBe(translation);
        });
    }
    it('preserves the documented fallback for an unknown event', () => {
        expect(etiquetaTipoEvento('future_unknown_event')).toBe('future_unknown_event');
    });
});
