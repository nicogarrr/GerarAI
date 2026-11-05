import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Medido en prod (5-nov-2026): la campana /alerts se prefetcheada en cada
// carga de página autenticada (129 ms en vacío, hasta 3,8 s bajo carga) y la
// barra inferior móvil añade 5 destinos más. IntentLink (intención: hover,
// foco o primer toque) ya existe y usan Sidebar y NavItems; esta guarda fija
// que la campana y la barra móvil también pasan por ahí.

test('la campana de alertas no usa Link plano (prefetch al montar)', () => {
    const header = readFileSync('components/Header.tsx', 'utf8');
    assert.match(header, /<IntentLink href="\/alerts"/);
    assert.doesNotMatch(header, /<Link href="\/alerts"/);
});

test('la barra inferior móvil navega solo con IntentLink', () => {
    const bottom = readFileSync('components/layout/BottomNav.tsx', 'utf8');
    assert.doesNotMatch(bottom, /from 'next\/link'/);
    assert.match(bottom, /<IntentLink[\s\S]*?href=\{item\.href\}/);
});
