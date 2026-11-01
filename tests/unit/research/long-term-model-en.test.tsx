import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LongTermModelPanel } from '@/components/research/FundamentalModelPanels';
import { createTranslator } from '@/lib/i18n/translate';

describe('LongTermModelPanel · idioma', () => {
    it('sin modelo, en inglés', () => {
        const html = renderToStaticMarkup(<LongTermModelPanel model={null} t={createTranslator('en')} locale="en" />);
        expect(html).toContain('Long-term fundamental model');
        expect(html).toContain("The model couldn&#x27;t be built with the available data.");
    });

    it('sin traductor sigue en español', () => {
        const html = renderToStaticMarkup(<LongTermModelPanel model={null} />);
        expect(html).toContain('Modelo fundamental a largo plazo');
    });
});
