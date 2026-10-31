/**
 * Guarda de copy de backend caído (F158a): la app solo sabe que la consulta
 * al servidor falló - por red (sin contacto) o por un 5xx (contactó y el
 * servidor no pudo completarla). El copy no puede afirmar nada que no sea
 * cierto en AMBOS casos: ni ubicación («backend local»), ni estado
 * («apagado», «no está en marcha», «no responde»), ni imposibilidad de
 * contacto («no logra contactar», falso en un 5xx), ni seguridad de datos
 * («Tus datos están a salvo», sin evidencia). Lo comprobado: el servidor no
 * ha podido completar la consulta; reintenta.
 * Ejecución: node --experimental-strip-types --test scripts/backend-offline-copy-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const surfaces = [
    join(here, '..', 'components/system/BackendOffline.tsx'),
    join(here, '..', 'app/(root)/screener/page.tsx'),
];

const UNVERIFIABLE = [
    'backend local',
    'no está en marcha',
    'apagado',
    'arrancando',
    'no responde',
    'no logra contactar',
    'Tus datos están a salvo',
];

void test('el copy de backend caído es cierto tanto en fallo de red como en 5xx', () => {
    for (const path of surfaces) {
        const src = readFileSync(path, 'utf8');
        for (const claim of UNVERIFIABLE) {
            assert.ok(!src.includes(claim), `${path}: afirmación no comprobable «${claim}»`);
        }
        const dict = JSON.parse(readFileSync(join(here, '..', 'lib/i18n/messages/es/ui.json'), 'utf8'));
        assert.ok(dict.system.failedDetail.includes('no ha podido completar la consulta'), 'diccionario: consulta no completada');
        assert.ok(dict.system.failedDetail.includes('Reintenta en unos segundos'), 'diccionario: reintento');
        assert.ok(
            src.includes('no ha podido completar la consulta') || src.includes("ui.system.failedDetail"),
            `${path}: el copy describe lo comprobado (consulta no completada)`,
        );
        assert.ok(
            src.includes('Reintenta en unos segundos') || src.includes("ui.system.failedDetail"),
            `${path}: acción honesta (reintento, sin prometer resultado)`,
        );
    }
});
