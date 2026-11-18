/**
 * Guard de las notas de retraso del panel /mercados (lib/i18n/messages/*):
 * cada nota de grupo afirma un retraso MEDIDO y FECHADO (qué se midió y
 * cuándo), nunca una frescura genérica sin medir. Nace 18-nov-2026 tras
 * medir el retraso real del feed gratuito de Yahoo por grupo (ver el
 * comentario del catálogo en lib/market/live-quotes.ts y
 * scripts/verify-live-markets.mjs, la herramienta de medición).
 *
 * Reglas:
 * - Cada nota de grupo (es y en) lleva "medido/medida" (es) o "measured"
 *   (en) y una fecha "d-mmm-aaaa" (p.ej. 18-nov-2026 / Nov 18, 2026).
 * - Cada nota se presenta como MUESTRA fechada, no como latencia garantizada
 *   (auditor 18-nov-2026: el retraso del feed gratuito cambia sin aviso).
 * - La cifra fina 603-609 s solo aparece junto a ES=F: se midió en ese
 *   contrato, no en todos los futuros (auditor 18-nov-2026).
 * - Ninguna nota, caption ni título afirma "tiempo real", "en directo" o
 *   "live": la frescura la dice la hora y la antigüedad de cada fila, y el
 *   retraso medido lo dice la nota.
 *
 * Ejecución: node --experimental-strip-types --test scripts/live-markets-delay-notes-guard.test.ts
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const es = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/markets.json'), 'utf8'));
const en = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/en/markets.json'), 'utf8'));

const GROUPS = ['indice', 'futuro', 'accion', 'materia', 'divisa'] as const;
// Fecha fechada estilo repo: "18-nov-2026" (es) o "Nov 18, 2026" (en).
const DATE_ES = /\b\d{1,2}-[a-z]{3}-\d{4}\b/;
const DATE_EN = /\b[A-Z][a-z]{2} \d{1,2}, \d{4}\b/;
const UNMEASURED_ES = /tiempo real|en directo|hora real/i;
const UNMEASURED_EN = /real[- ]time|\blive\b/i;

test('cada nota de grupo afirma un retraso MEDIDO y FECHADO (es y en)', () => {
    for (const key of GROUPS) {
        const noteEs = es.live.notes[key] as string;
        const noteEn = en.live.notes[key] as string;
        assert.ok(noteEs && noteEn, `nota ausente para ${key}`);
        assert.match(noteEs, /\bmedid[ao]\b/i, `nota es de ${key} sin "medido/a": ${noteEs}`);
        assert.match(noteEs, DATE_ES, `nota es de ${key} sin fecha d-mmm-aaaa: ${noteEs}`);
        assert.match(noteEn, /\bmeasured\b/i, `nota en de ${key} sin "measured": ${noteEn}`);
        assert.match(noteEn, DATE_EN, `nota en de ${key} sin fecha Mmm d, yyyy: ${noteEn}`);
    }
});

test('cada nota se presenta como MUESTRA, no como latencia garantizada', () => {
    for (const key of GROUPS) {
        assert.match(es.live.notes[key] as string, /no (es )?una latencia garantizada/i, `nota es de ${key} sin el marco de muestra`);
        assert.match(en.live.notes[key] as string, /not a guaranteed latency/i, `nota en de ${key} sin el marco de muestra`);
    }
});

test('la cifra fina 603-609 s solo se afirma junto a ES=F (donde se midió)', () => {
    for (const [lang, notes] of [['es', es.live.notes], ['en', en.live.notes]] as const) {
        for (const key of GROUPS) {
            const note = notes[key] as string;
            if (note.includes('603-609')) {
                assert.ok(note.includes('ES=F'), `nota ${lang} de ${key} cita 603-609 s sin acotarlo a ES=F: ${note}`);
            }
        }
    }
});

test('ninguna superficie del panel afirma frescura genérica sin medir', () => {
    for (const key of GROUPS) {
        assert.doesNotMatch(es.live.notes[key] as string, UNMEASURED_ES, `nota es de ${key}`);
        assert.doesNotMatch(en.live.notes[key] as string, UNMEASURED_EN, `nota en de ${key}`);
    }
    for (const surface of ['tableCaption', 'pageDescription', 'metaDescription'] as const) {
        assert.doesNotMatch(es.live[surface] ?? es[surface] ?? '', UNMEASURED_ES, `es ${surface}`);
        assert.doesNotMatch(en.live[surface] ?? en[surface] ?? '', UNMEASURED_EN, `en ${surface}`);
    }
});
