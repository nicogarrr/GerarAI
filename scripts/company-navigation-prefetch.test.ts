import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');

test('las pestañas de la ficha no prefetchean: cada _rsc cuesta 200-450 ms de servidor', () => {
    // Medido en prod (5-nov-2026, cuenta de pruebas): cargar /research/CHTR
    // dispara 5-6 peticiones _rsc de prefetch (una por pestaña), cada una un
    // render RSC completo con sus workspaces de backend. prefetch={false}
    // mantiene la navegación igual de rápida al pulsar (conexión caliente) y
    // quita esa CPU de la VM.
    assert.match(source, /prefetch=\{false\}/);
    // Un solo <Link> en el componente (la fila de pestañas lo genera en map).
    assert.equal(source.match(/<Link\b/g)?.length, 1);
    assert.equal(source.match(/prefetch=\{false\}/g)?.length, 1);
});
