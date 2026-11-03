import { describe, expect, it } from 'vitest';

import { valuationMethodView } from '@/lib/research/valuation-method';

describe('valuationMethodView', () => {
  it('devuelve null sin etiqueta, aviso ni rango (la ficha no cambia)', () => {
    expect(valuationMethodView({ valuation_label: null })).toBeNull();
    expect(valuationMethodView(undefined)).toBeNull();
  });

  it('AMZN-like: etiqueta, notas, rango y qué descuenta el precio', () => {
    const view = valuationMethodView({
      valuation_label: 'estimado, capex normalizado · estimado, DCF multietapa',
      valuation_notes: ['Capex normalizado: en el FY2025 el capex fue 131.819 M…'],
      fair_value_range: {
        low: 85.1,
        high: 315.5,
        currency: 'USD',
        components: [
          { method: 'dcf', label: 'DCF (estimado, capex normalizado)', value: 85.1 },
          { method: 'pe', label: 'PER de peers (mediana 44)', value: 315.5, low: 202.8, high: 585.3 },
        ],
      },
      reverse_dcf: { explanation_es: 'El precio de 251,36 descuenta un crecimiento de ingresos del 32,0 % anual…' },
    });
    expect(view?.label).toContain('capex normalizado');
    expect(view?.notes).toHaveLength(1);
    expect(view?.range?.low).toBe(85.1);
    expect(view?.range?.components).toHaveLength(2);
    expect(view?.priceImplies).toContain('descuenta');
  });

  it('el aviso 0,2x–5x se muestra aunque no haya etiqueta; un rango de un solo método no es rango', () => {
    const view = valuationMethodView({
      plausibility_warning: { message_es: 'El valor del DCF es 0,10 veces el precio…' },
      fair_value_range: { low: 10, high: 10, components: [{ method: 'dcf', label: 'DCF', value: 10 }] },
      reverse_dcf: { explanation_es: 'x' },
    });
    expect(view?.warning).toContain('0,10 veces');
    expect(view?.range).toBeNull();
    expect(view?.priceImplies).toBeNull();
  });
});
