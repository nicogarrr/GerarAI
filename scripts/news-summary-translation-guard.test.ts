/**
 * Guard de la traducción del resumen de una noticia (encargo Nico 19/10):
 * traducción bajo demanda con provenance, sin relleno de fallo, y el tipo
 * con summary + summary_translation serializados por el motor.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const component = readFileSync('components/research/NewsSummary.tsx', 'utf8');
const flow = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
const types = readFileSync('lib/actions/research.actions.ts', 'utf8');
const proxy = readFileSync('app/api/news/[eventId]/translation/summary/route.ts', 'utf8');

test('provenance siempre que se muestra una traducción y cero relleno', () => {
    const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).translate;
    assert.ok(component.includes("<span>{t('research.translate.autoLabel')}</span>"));
    assert.equal(es.autoLabel, 'Traducción automática · español');
    assert.ok(component.includes("t('research.translate.viewOriginal')"));
    assert.equal(es.viewOriginal, 'Ver original');
    // Al fallar se queda el original; solo se permite el aviso de estado corto del botón.
    const unavailableMentions = component.split('no disponible').length - 1;
    assert.ok(unavailableMentions <= 1, 'nada de meta-texto de fallo más allá del aviso de estado');
    assert.ok(unavailableMentions === 0 || (component.includes('role="status"') && component.includes("t('research.translate.genericFailure')") && es.genericFailure.startsWith('Traducción no disponible ahora mismo.')), 'el aviso va como status del botón');
    assert.ok(!component.includes('Resumen generado'), 'nunca inventar contenido: solo traducir');
});

test('la traducción es bajo demanda (botón), no automática al pintar', () => {
    assert.ok(component.includes("method: 'POST'"));
    assert.ok(component.includes('/translation/summary'));
    assert.ok(!component.includes('useEffect'), 'sin auto-fetch al montar: cuota frugal');
});

test('el flujo de noticias pinta el resumen en tarjeta móvil y tabla', () => {
    const uses = flow.split('NewsSummary event={event}').length - 1;
    assert.ok(uses >= 2, `NewsSummary en móvil y desktop (encontrado ${uses - 1})`);
});

test('el tipo y el proxy conservan la forma del contrato del titular', () => {
    assert.ok(types.includes('summary_translation?: {text: string; target_language: string; machine_translation: boolean} | null'));
    assert.ok(proxy.includes('/translation/summary'));
    assert.ok(proxy.includes("status:'unavailable'"), 'fallback honesto del proxy');
});
