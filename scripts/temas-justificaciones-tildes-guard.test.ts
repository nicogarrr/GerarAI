// Guard: las justificaciones curadas de los temas (texto visible en Temas)
// llevan sus tildes. Patrones sin tildar que no deben reaparecer.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('data-engine/app/services/market_themes.py', 'utf8');

test('ninguna justificación curada queda sin tildar', () => {
    const sinTildar = [
        'Conduccion', 'autonoma', 'autonomo', 'Deteccion', 'Edicion', 'genetica',
        'Secuenciacion', 'numero 1', 'suscripcion', 'Vision artificial', 'Monetizacion',
        'Electrica ', 'Imagenes', 'resolucion', 'paga despues', 'táctica militares',
    ];
    for (const texto of sinTildar) {
        assert.ok(!SRC.includes(texto), `texto sin tildar presente: ${texto}`);
    }
    assert.ok(SRC.includes('Comunicaciones tácticas militares'), 'concordancia tácticas');
});
