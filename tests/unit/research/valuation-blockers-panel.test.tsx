import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LongTermModelPanel } from '@/components/research/FundamentalModelPanels';
import { createTranslator } from '@/lib/i18n/translate';
import { MODELO_SIN_VALORACION } from './fixtures/long-term-model-sin-valoracion';

describe('LongTermModelPanel · N/D con causa', () => {
    it('es: cabecera dice que el valor/acción no es calculable y por qué', () => {
        const html = renderToStaticMarkup(<LongTermModelPanel model={MODELO_SIN_VALORACION} />);
        expect(html).toContain('valor/acción no calculable: falta la deuda neta actual · falta el número de acciones diluidas');
        // La causa aparece bajo el N/D de cada escenario, no solo en cabecera.
        expect(html).toContain('falta el número de acciones diluidas');
        expect(html).not.toContain('DCF skipped');
    });

    it('en: mismo contenido traducido', () => {
        const html = renderToStaticMarkup(<LongTermModelPanel model={MODELO_SIN_VALORACION} t={createTranslator('en')} locale="en" />);
        expect(html).toContain('value per share not computable: current net debt missing · diluted share count missing');
    });

    it('publicable con inputs pendientes no se anuncia como «no publicable»', () => {
        const model = { ...MODELO_SIN_VALORACION, missing_inputs: ['driver_xyz'] };
        const html = renderToStaticMarkup(<LongTermModelPanel model={model} />);
        expect(html).toContain('Datos operativos pendientes: driver xyz');
        expect(html).not.toContain('Modelo no publicable');
    });

    it('no publicable de verdad mantiene el aviso de siempre', () => {
        const model = { ...MODELO_SIN_VALORACION, publishable: false, missing_inputs: ['driver_xyz'] };
        const html = renderToStaticMarkup(<LongTermModelPanel model={model} />);
        expect(html).toContain('Modelo no publicable: faltan driver xyz.');
    });

    it('con valoración en algún escenario no hay etiqueta de «no calculable»', () => {
        const model = {
            ...MODELO_SIN_VALORACION,
            scenarios: {
                ...MODELO_SIN_VALORACION.scenarios,
                base: { ...MODELO_SIN_VALORACION.scenarios.base, valuation: { value_per_share: 12.3, enterprise_value: 1, equity_value: 1 }, valuation_blockers: [], valuation_note: null },
            },
        };
        const html = renderToStaticMarkup(<LongTermModelPanel model={model} />);
        expect(html).not.toContain('no calculable');
    });
});
