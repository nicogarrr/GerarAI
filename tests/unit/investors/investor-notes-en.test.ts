import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { OWNERSHIP_TEXT_EN, ownershipLimitations, ownershipNote } from '@/lib/research/ownership-display';

// Las frases salen de investor_portfolio.py; se juntan los literales que Python
// concatena entre paréntesis para poder buscarlas enteras.
// Las notas de fila salen de investor_portfolio.py; los avisos de
// comparación incompleta, de manager_holding_ingestion_service.py; la nota de
// total incompleto del resumen y la ficha, de investors.py.
const BACKEND = ['investor_portfolio.py', 'manager_holding_ingestion_service.py', 'investors.py']
    .map((file) => readFileSync(path.resolve(__dirname, `../../../data-engine/app/services/${file}`), 'utf8'))
    .join('\n')
    .replace(/"\s*\n\s*"/g, '');

// Aviso anterior de comparación incompleta: el motor nuevo (#5479) ya no lo
// emite, pero la traducción se mantiene mientras pueda convivir con un
// backend desplegado antes del cambio. No se exige en el código del motor.
const LEGACY_BACKEND_PHRASES = [
    'Comparación incompleta: faltan acciones válidas en uno o ambos periodos; no se infiere una compra, venta ni posición sin cambios.',
];

describe('cartera de un inversor: notas del backend en inglés', () => {
    it('el backend sigue mandando cada frase de la tabla', () => {
        for (const sentence of Object.keys(OWNERSHIP_TEXT_EN)) {
            if (LEGACY_BACKEND_PHRASES.includes(sentence)) continue;
            expect(BACKEND).toContain(sentence);
        }
    });

    it('el aviso nuevo y el anterior de comparación incompleta salen en inglés', () => {
        expect(ownershipNote('Comparación incompleta: faltan cantidades válidas o las unidades no son comparables; no se infiere una compra, venta ni posición sin cambios.', 'en'))
            .toBe('Incomplete comparison: valid quantities are missing or the units are not comparable; no purchase, sale or unchanged position is inferred.');
        expect(ownershipNote('Comparación incompleta: faltan acciones válidas en uno o ambos periodos; no se infiere una compra, venta ni posición sin cambios.', 'en'))
            .toBe('Incomplete comparison: valid share counts are missing in one or both periods; no purchase, sale or unchanged position is inferred.');
    });

    it('la nota de total incompleto del resumen y la ficha sale en inglés', () => {
        expect(ownershipNote('Valor total incompleto: faltan importes declarados de algunas posiciones; no se calculan pesos con un subtotal.', 'en'))
            .toBe('Incomplete total value: declared amounts for some positions are missing; no weights are derived from a subtotal.');
        expect(ownershipNote('Sin datos: no presenta 13F', 'en')).toBe('No data: no 13F on file.');
    });

    it('con English la nota de cada fila sale en inglés', () => {
        expect(ownershipNote('Opción (put/call): importe nocional, no posición en acciones.', 'en')).toBe('Option (put/call): notional amount, not a share position.');
        expect(ownershipNote('Codigo G (donacion/transferencia): no es compra ni venta en mercado.', 'en')).toBe('Code G (gift/transfer): not an open-market purchase or sale.');
        expect(ownershipNote('Diferencia entre dos 13F trimestrales (fecha = cierre del trimestre, no del trade).', 'en'))
            .toBe('Difference between two quarterly 13Fs (date = quarter end, not the trade date).');
        for (const english of Object.values(OWNERSHIP_TEXT_EN)) expect(english).not.toMatch(/[áéíóúñ]| de | sin | no es /);
    });

    it('el aviso de un gestor sin 13F sale en inglés; el del 13F (ya en inglés) no cambia', () => {
        const sin13f = Object.keys(OWNERSHIP_TEXT_EN).find((key) => key.startsWith('Sin 13F'))!;
        expect(ownershipLimitations(sin13f, 'en')).toMatch(/^No 13F: only positions documented in 13D\/Forms 3\/4\./);
        expect(ownershipLimitations(['Amendments are separate immutable filings'], 'en')).toBe('Amendments are separate immutable filings');
    });

    it('en castellano y con textos nuevos, tal cual', () => {
        expect(ownershipNote('Opción (put/call): importe nocional, no posición en acciones.', 'es')).toBe('Opción (put/call): importe nocional, no posición en acciones.');
        expect(ownershipNote('Nota nueva del backend', 'en')).toBe('Nota nueva del backend');
        expect(ownershipLimitations(['Amendments are separate immutable filings'], 'es')).toBe('Las enmiendas son declaraciones inmutables independientes');
    });
});
