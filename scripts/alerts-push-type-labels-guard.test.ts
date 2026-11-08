/**
 * Guarda de las etiquetas de tipos de aviso: PushNotifications y
 * EmailNotifications pintan la MISMA tabla tipo -> clave de diccionario,
 * importada de lib/alerts/push-type-labels.ts. Las dos tenían una copia
 * local idéntica que podía desviarse al dar de alta un tipo nuevo.
 *
 * Ejecución: node --experimental-strip-types --test scripts/alerts-push-type-labels-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const email = readFileSync('components/alerts/EmailNotifications.tsx', 'utf8');
const push = readFileSync('components/alerts/PushNotifications.tsx', 'utf8');
const shared = readFileSync('lib/alerts/push-type-labels.ts', 'utf8');
const types = readFileSync('lib/alerts/push-event-types.ts', 'utf8');

const KEYS = [
    'macro_event',
    'earnings',
    'dca_levels',
    'new_filing',
    'thesis_broken',
    'insiders',
    'shorts_rising',
    'daily_digest',
];

describe('etiquetas de tipos de aviso compartidas', () => {
    it('los dos componentes importan la tabla compartida', () => {
        for (const [name, source] of [['EmailNotifications', email], ['PushNotifications', push]] as const) {
            assert.ok(
                source.includes("from '@/lib/alerts/push-type-labels'"),
                name + ' importa lib/alerts/push-type-labels',
            );
            assert.ok(
                source.includes('PUSH_TYPE_LABEL_KEYS['),
                name + ' pinta con la tabla compartida',
            );
        }
    });

    it('no quedan copias locales de la tabla en los componentes', () => {
        for (const [name, source] of [['EmailNotifications', email], ['PushNotifications', push]] as const) {
            assert.ok(
                !source.includes('Record<PushEventType, TranslationKey>'),
                name + ' sin tabla local duplicada',
            );
        }
    });

    it('la tabla compartida cubre exactamente los tipos de PUSH_EVENT_TYPES', () => {
        for (const key of KEYS) {
            assert.ok(shared.includes(key + ':'), 'la tabla compartida tiene ' + key);
            assert.ok(types.includes("'" + key + "'"), 'PUSH_EVENT_TYPES declara ' + key);
        }
        for (const line of shared.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed.includes(": 'alerts.push.types.")) continue;
            const key = trimmed.slice(0, trimmed.indexOf(':'));
            assert.ok(KEYS.includes(key), key + ' existe en PUSH_EVENT_TYPES');
        }
    });
});
